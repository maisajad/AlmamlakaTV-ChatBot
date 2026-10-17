"""FastAPI app: the chat API plus the static single-page UI.

    uvicorn app.main:app --port 7860

The session id travels in the JSON body rather than a cookie, so the app also works when
embedded in an iframe, where third-party cookies are often blocked.

Admin (uploading PDFs) is enabled only when ADMIN_TOKEN is set.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import re
import secrets
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.ingest import PDF_DIR
from app.kb import MAX_UPLOAD_BYTES, KnowledgeBase, UploadError
from app.pipeline import ChatBot
from app.retrieval import ROOT
from app.sessions import redis_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC = ROOT / "static"
QUALITY_REPORT = ROOT / "data" / "quality-report.json"  # served by /api/quality-report, behind the access code
DEBUG = os.environ.get("DEBUG") == "1"  # include routing/retrieval details in replies
PUBLIC_FIELDS = ("session_id", "status", "language", "answer", "citations", "conflicts")


def build_state() -> tuple[ChatBot, KnowledgeBase]:
    """Load the knowledge base (re-ingesting if the PDFs changed) and the chat bot over it."""
    kb = KnowledgeBase(redis=redis_client())
    bot = ChatBot(answerer=kb.load())
    kb.on_change = lambda answerer: setattr(bot, "answerer", answerer)  # hot-swap after uploads
    return bot, kb


def log_memory(stage: str) -> None:
    """Startup memory in the host's logs: the free instance is killed above 512 MB."""
    try:
        import resource  # Unix only
        peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KB on Linux
        with open("/proc/self/status") as f:
            rss_mb = next(int(line.split()[1]) for line in f if line.startswith("VmRSS")) / 1024
        logging.getLogger(__name__).info("memory %s: %.0f MB now, %.0f MB peak", stage, rss_mb, peak_mb)
    except (ImportError, OSError, StopIteration):
        pass


def release_freed_memory() -> None:
    """Return heap freed during startup (the model load's temporary buffers) to the OS."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:  # not glibc (Windows, macOS)
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.bot, app.state.kb = build_state()
    release_freed_memory()
    log_memory("after startup")
    yield


app = FastAPI(title="Almamlaka TV Assistant", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def revalidate_static(request, call_next):
    """Browsers must re-check the page and its assets on every load (cheap: ETag -> 304), so a
    new deploy is never mixed with a cached old app.js."""
    response = await call_next(request)
    if request.url.path in ("/", "/admin", "/quality") or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response

app.mount("/static", StaticFiles(directory=STATIC), name="static")


class ChatRequest(BaseModel):
    message: str = Field(max_length=5000)  # the pipeline replies "too long" above its own, lower limit
    session_id: str | None = Field(default=None, max_length=100)


class ResetRequest(BaseModel):
    session_id: str = Field(max_length=100)


def asset_version() -> str:
    """Hash of the front-end files. Stamped onto asset URLs so browsers can't keep an old copy."""
    digest = hashlib.sha256()
    for path in sorted(STATIC.glob("*.*")):
        digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def page(name: str) -> HTMLResponse:
    """A static HTML page with its asset URLs stamped with the current asset version."""
    html = (STATIC / name).read_text(encoding="utf-8")
    html = re.sub(r'(/static/[\w.-]+\.(?:js|css))"', rf'\1?v={asset_version()}"', html)
    return HTMLResponse(html)


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    return page("index.html")


@app.get("/quality", include_in_schema=False)
def quality_page() -> HTMLResponse:
    return page("quality.html")


@app.get("/admin", include_in_schema=False)
def admin_page() -> HTMLResponse:
    if not os.environ.get("ADMIN_TOKEN"):
        raise HTTPException(404)
    return page("admin.html")


def bearer(request: Request) -> str:
    return request.headers.get("authorization", "").removeprefix("Bearer ").strip()


def access_tokens() -> list[str]:
    """User access codes: ACCESS_TOKENS, comma-separated (one per person makes revoking easy).
    Unset or empty means the assistant is open to everyone."""
    return [t.strip() for t in os.environ.get("ACCESS_TOKENS", "").split(",") if t.strip()]


def user_allowed(request: Request) -> bool:
    codes = access_tokens()
    if not codes:
        return True
    if admin := os.environ.get("ADMIN_TOKEN"):
        codes.append(admin)  # the admin can use the chat too
    sent = bearer(request).encode()
    # Compare against every code (no early exit), in constant time.
    return sum(secrets.compare_digest(sent, code.encode()) for code in codes) > 0


def require_user(request: Request) -> None:
    if not user_allowed(request):
        raise HTTPException(401, "Access code required.")


@app.get("/api/auth")
def auth_status(request: Request) -> dict:
    """Whether an access code is needed, and whether the one sent (if any) is valid."""
    return {"required": bool(access_tokens()), "ok": user_allowed(request)}


@app.get("/api/quality-report")
def quality_report(request: Request) -> Response:
    """The /quality page's data (it quotes the documents, so it needs the access code too)."""
    require_user(request)
    if not QUALITY_REPORT.exists():
        raise HTTPException(404, "No test report yet.")
    return FileResponse(QUALITY_REPORT, media_type="application/json")


@app.get("/pdfs/{name}", include_in_schema=False)
def pdf(name: str, request: Request) -> Response:
    """Source documents for the viewer: committed PDFs from disk, uploaded ones from storage."""
    require_user(request)
    if name != os.path.basename(name):
        raise HTTPException(404)
    path = PDF_DIR / name
    if path.is_file():
        return FileResponse(path, media_type="application/pdf")
    data = app.state.kb.pdf_bytes(name)
    if data is None:
        raise HTTPException(404)
    return Response(data, media_type="application/pdf")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "sessions": app.state.bot.sessions.kind}


def require_admin(request: Request) -> None:
    token = os.environ.get("ADMIN_TOKEN")
    if not token:
        raise HTTPException(404)  # admin is off: don't even admit it exists
    if not secrets.compare_digest(bearer(request).encode(), token.encode()):
        raise HTTPException(401, "Wrong admin token.")


@app.get("/api/admin/status")
def admin_status(request: Request) -> dict:
    require_admin(request)
    return app.state.kb.status()


@app.post("/api/admin/documents")
async def admin_upload(request: Request) -> dict:
    """Raw PDF in the body; file name in X-Filename. Ingested and live when this returns."""
    require_admin(request)
    data = await request.body()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"PDFs can be at most {MAX_UPLOAD_BYTES // 2**20} MB.")
    try:
        return await run_in_threadpool(app.state.kb.add, request.headers.get("x-filename", ""), data)
    except UploadError as e:
        raise HTTPException(400, str(e)) from e


@app.delete("/api/admin/documents/{name}")
async def admin_delete(name: str, request: Request) -> dict:
    require_admin(request)
    try:
        return await run_in_threadpool(app.state.kb.remove, name)
    except UploadError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/chat")
def chat(body: ChatRequest, request: Request) -> dict:
    # A sync endpoint: FastAPI runs it in a worker thread, so slow model calls don't block the loop.
    require_user(request)
    result = app.state.bot.chat(body.session_id, body.message)
    return result if DEBUG else {k: result[k] for k in PUBLIC_FIELDS}


@app.post("/api/chat/stream")
def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
    """Server-Sent Events: the draft answer text while it is written, then the
    same verified reply /api/chat returns, as a final "result" event."""
    require_user(request)
    events: queue.Queue = queue.Queue()
    done = object()

    def run() -> None:
        try:
            result = app.state.bot.chat(body.session_id, body.message, on_event=events.put)
            events.put({"type": "result", "reply": result if DEBUG else {k: result[k] for k in PUBLIC_FIELDS}})
        except Exception:  # never leave the client hanging on a broken stream
            logging.getLogger(__name__).exception("stream failed")
            events.put({"type": "error"})
        finally:
            events.put(done)

    threading.Thread(target=run, daemon=True).start()

    def sse():
        while (event := events.get()) is not done:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/reset")
def reset(body: ResetRequest, request: Request) -> dict:
    require_user(request)
    app.state.bot.sessions.reset(body.session_id)
    return {"ok": True}
