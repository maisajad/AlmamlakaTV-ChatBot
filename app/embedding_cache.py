"""Passage embeddings computed at image build time, so startup doesn't have to.

Embedding every chunk at startup briefly needs ~75 MB on top of the model, and on a
fraction of a CPU it is slow; on a 512 MB instance that spike was enough to get the
service killed. The Docker build runs `python -m app.embedding_cache`, which stores the
vectors keyed by a hash of the exact text embedded. At startup, cached vectors are
loaded and only text without one (an uploaded PDF, edited chunks) is embedded, one at a time.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Callable

import numpy as np

from app.ingest import ROOT

log = logging.getLogger(__name__)
CACHE_PATH = ROOT / "data" / "embeddings.npz"


def key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def load(model_id: str | None, path: Path = CACHE_PATH) -> dict[str, np.ndarray]:
    """Cached vectors, only if they were made by this exact model (anything else would mix spaces)."""
    if not model_id or not path.exists():
        return {}
    data = np.load(path)
    if str(data["model"]) != model_id:
        return {}
    return dict(zip(data["keys"].tolist(), data["vectors"]))


def embed_passages(texts: list[str], embed: Callable[[list[str]], np.ndarray], model_id: str | None,
                   path: Path = CACHE_PATH) -> np.ndarray:
    cache = load(model_id, path)
    missing = [t for t in texts if key(t) not in cache]
    if missing:
        log.info("embedding %d of %d passages (not in the build-time cache)", len(missing), len(texts))
        for text in missing:  # one at a time: small activation memory
            cache[key(text)] = embed([text])[0]
    return np.stack([cache[key(t)] for t in texts]).astype(np.float32)


def build(path: Path = CACHE_PATH) -> int:
    """Embed every committed chunk and write the cache. Run at image build time."""
    from app.embeddings import OnnxEmbedder
    from app.retrieval import index_text, load_chunks

    model = OnnxEmbedder()
    texts = [f"passage: {index_text(c)}" for c in load_chunks()]
    vectors = np.stack([model.encode([t])[0] for t in texts]).astype(np.float32)
    np.savez(path, model=np.array(model.cache_id), keys=np.array([key(t) for t in texts]), vectors=vectors)
    return len(texts)


if __name__ == "__main__":
    print(f"cached {build()} passage embeddings -> {CACHE_PATH.relative_to(ROOT)}")
