"""The current knowledge base: which PDFs, their chunks and conflicts, and the Answerer over them.

New PDFs need no scripts run by hand:
- PDFs committed to data/pdfs are fingerprinted at startup; if they changed since
  chunks.json was built, they are re-ingested on the spot.
- PDFs uploaded on the admin page are validated, stored (in Redis when available, so they
  survive restarts) and ingested immediately; the new knowledge base replaces the old one
  without a restart.
Either way, conflict detection reruns in the background. Until it finishes, previously known
conflicts that still verify against the new chunks stay in effect.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
from pathlib import Path
from typing import Callable

from app import llm
from app.answer import Answerer
from app.conflicts import find_conflicts, load_registry, valid_for
from app.ingest import CHUNKS_PATH, build, fingerprint, parse_pdf, repo_sources
from app.retrieval import Retriever

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 5 * 2**20
MAX_UPLOAD_PAGES = 40
MAX_UPLOADS = 10
SAFE_NAME = re.compile(r"^[\w\- .()]{1,80}\.pdf$", re.IGNORECASE)


class UploadError(ValueError):
    """Shown to the admin as-is."""


class KnowledgeBase:
    def __init__(self, redis=None, call: Callable[..., dict] = llm.structured_call, model=None,
                 on_change: Callable[[Answerer], None] | None = None, detect_in_background: bool = True):
        self.redis = redis
        self.call = call
        self.model = model
        self.on_change = on_change or (lambda answerer: None)
        self.detect_in_background = detect_in_background
        self._memory_uploads: dict[str, bytes] = {}
        self._memory_conflicts: dict[str, list] = {}
        self._lock = threading.RLock()
        self.state: dict = {}
        self.answerer: Answerer | None = None

    # ---------- uploads and conflict cache (Redis when available) ----------

    def uploads(self) -> dict[str, bytes]:
        if self.redis is not None:
            return {name: base64.b64decode(data) for name, data in self.redis.hgetall("kb:uploads").items()}
        return dict(self._memory_uploads)

    def _store_upload(self, name: str, data: bytes | None) -> None:
        if self.redis is not None:
            if data is None:
                self.redis.hdel("kb:uploads", name)
            else:
                self.redis.hset("kb:uploads", name, base64.b64encode(data).decode())
        elif data is None:
            self._memory_uploads.pop(name, None)
        else:
            self._memory_uploads[name] = data

    def _cached_conflicts(self, fp: str) -> list | None:
        if self.redis is not None:
            raw = self.redis.get(f"kb:conflicts:{fp}")
            return json.loads(raw) if raw else None
        return self._memory_conflicts.get(fp)

    def _cache_conflicts(self, fp: str, conflicts: list) -> None:
        if self.redis is not None:
            self.redis.set(f"kb:conflicts:{fp}", json.dumps(conflicts, ensure_ascii=False))
        else:
            self._memory_conflicts[fp] = conflicts

    # ---------- building ----------

    def load(self) -> Answerer:
        """(Re)build from the repo PDFs plus uploads; swaps the answerer in place."""
        with self._lock:
            repo = repo_sources()
            uploads = sorted(self.uploads().items())
            sources = repo + uploads
            fp = fingerprint(sources)

            committed = json.loads(CHUNKS_PATH.read_text(encoding="utf-8")) if CHUNKS_PATH.exists() else {}
            if committed.get("fingerprint") == fp:
                data = committed
            else:
                log.info("PDFs changed (fingerprint %s): re-ingesting %d documents", fp, len(sources))
                data = build(sources)

            registry = load_registry()
            if registry.get("fingerprint") == fp:
                conflicts, conflict_state = registry["conflicts"], "reviewed"
            elif (cached := self._cached_conflicts(fp)) is not None:
                conflicts, conflict_state = cached, "detected"
            else:
                # Keep known conflicts that still verify, and look for new ones in the background.
                conflicts, conflict_state = valid_for(registry["conflicts"], data["chunks"]), "detecting"

            upload_names = {name for name, _ in uploads}
            self.state = {
                "fingerprint": fp,
                "documents": [{**doc, "source": "upload" if doc["file"] in upload_names else "repo",
                               "chunks": sum(c["doc_id"] == doc["doc_id"] for c in data["chunks"])}
                              for doc in data["documents"]],
                "chunks": data["chunks"],
                "conflicts": conflicts,
                "conflict_state": conflict_state,
            }
            self._swap()
            if conflict_state == "detecting":
                self._start_detection(fp, data["chunks"])
            return self.answerer

    def _swap(self) -> None:
        retriever = Retriever(self.state["chunks"], model=self._embedder(),
                              related_groups=[[cl["chunk_id"] for cl in c["claims"]] for c in self.state["conflicts"]])
        self.answerer = Answerer(retriever=retriever, conflicts=self.state["conflicts"], call=self.call)
        self.on_change(self.answerer)

    def _embedder(self):
        if self.model is None:
            from app.embeddings import OnnxEmbedder
            self.model = OnnxEmbedder()
        return self.model

    def _start_detection(self, fp: str, chunks: list[dict]) -> None:
        def run() -> None:
            try:
                kept, dropped = find_conflicts(chunks, call=self.call)
                log.info("conflict detection for %s: %d kept, %d dropped", fp, len(kept), len(dropped))
                self._cache_conflicts(fp, kept)
                with self._lock:
                    if self.state.get("fingerprint") == fp:  # nothing changed meanwhile
                        self.state.update(conflicts=kept, conflict_state="detected")
                        self._swap()
            except Exception:  # noqa: BLE001 - keep serving with the conflicts we have
                log.exception("conflict detection failed")
                with self._lock:
                    if self.state.get("fingerprint") == fp:
                        self.state["conflict_state"] = "failed"

        if self.detect_in_background:
            threading.Thread(target=run, daemon=True).start()
        else:
            run()

    # ---------- admin operations ----------

    def add(self, name: str, data: bytes) -> dict:
        name = Path(name or "").name.strip()
        if not SAFE_NAME.match(name):
            raise UploadError("Use a .pdf file name with letters, digits, spaces, dots, dashes or underscores.")
        if not data.startswith(b"%PDF-"):
            raise UploadError("That file is not a PDF.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise UploadError(f"PDFs can be at most {MAX_UPLOAD_BYTES // 2**20} MB.")
        repo_names = {n for n, _ in repo_sources()}
        if name in repo_names:
            raise UploadError("A built-in document already has that name.")
        current = self.uploads()
        if name not in current and len(current) >= MAX_UPLOADS:
            raise UploadError(f"At most {MAX_UPLOADS} uploaded documents.")
        try:
            doc, chunks = parse_pdf(name, data)
        except Exception as e:  # noqa: BLE001 - malformed PDFs raise all sorts of things
            raise UploadError(f"Couldn't read that PDF ({e.__class__.__name__}).") from e
        if not chunks:
            raise UploadError("No text found in that PDF. Scanned PDFs need OCR first.")
        if max(max(c["pages"]) for c in chunks) > MAX_UPLOAD_PAGES:
            raise UploadError(f"PDFs can have at most {MAX_UPLOAD_PAGES} pages.")
        self._store_upload(name, data)
        self.load()
        return self.status()

    def remove(self, name: str) -> dict:
        if name not in self.uploads():
            raise UploadError("Only uploaded documents can be removed.")
        self._store_upload(name, None)
        self.load()
        return self.status()

    def status(self) -> dict:
        return {
            "fingerprint": self.state.get("fingerprint"),
            "documents": self.state.get("documents", []),
            "conflicts": [{"topic": c["topic"], "claims": len(c["claims"])} for c in self.state.get("conflicts", [])],
            "conflict_state": self.state.get("conflict_state"),
            "storage": "redis" if self.redis is not None else "memory",
        }

    def pdf_bytes(self, name: str) -> bytes | None:
        """Uploaded PDFs are served from storage, so the source viewer works for them too."""
        return self.uploads().get(name)
