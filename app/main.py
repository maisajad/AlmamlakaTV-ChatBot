"""FastAPI app: the chat API plus the static single-page UI.

    uvicorn app.main:app --port 7860

The session id travels in the JSON body rather than a cookie: Hugging Face Spaces
serves apps inside an iframe, where third-party cookies are often blocked.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
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
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class ChatRequest(BaseModel):
    message: str = Field(max_length=5000)  # the pipeline replies "too long" above its own, lower limit
    session_id: str | None = Field(default=None, max_length=100)


class ResetRequest(BaseModel):
    session_id: str = Field(max_length=100)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


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
