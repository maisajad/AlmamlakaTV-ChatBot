"""FastAPI app: the chat API plus the static single-page UI.

    uvicorn app.main:app --port 7860

The session id travels in the JSON body rather than a cookie: Hugging Face Spaces
serves apps inside an iframe, where third-party cookies are often blocked.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.pipeline import ChatBot
from app.retrieval import ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC = ROOT / "static"
DEBUG = os.environ.get("DEBUG") == "1"  # include routing/retrieval details in replies
PUBLIC_FIELDS = ("session_id", "status", "language", "answer", "citations", "conflicts")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.bot = ChatBot()  # loads chunks, conflicts and the embedding model once
    yield


app = FastAPI(title="Almamlaka TV Assistant", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def revalidate_static(request, call_next):
    """Browsers must re-check the page and its assets on every load (cheap: ETag -> 304), so a
    new deploy is never mixed with a cached old app.js."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response

app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/pdfs", StaticFiles(directory=ROOT / "data" / "pdfs"), name="pdfs")  # source documents for the viewer


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


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = re.sub(r'(/static/[\w.-]+\.(?:js|css))"', rf'\1?v={asset_version()}"', html)
    return HTMLResponse(html)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict:
    # A sync endpoint: FastAPI runs it in a worker thread, so slow model calls don't block the loop.
    result = app.state.bot.chat(request.session_id, request.message)
    return result if DEBUG else {k: result[k] for k in PUBLIC_FIELDS}


@app.post("/api/reset")
def reset(request: ResetRequest) -> dict:
    app.state.bot.sessions.reset(request.session_id)
    return {"ok": True}
