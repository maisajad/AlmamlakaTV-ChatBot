"""Hybrid retrieval over the section chunks.

BM25 is good at exact figures and names ("$50,000", "Omar Fayez"); multilingual
embeddings (app/embeddings.py) handle paraphrases and Arabic questions against English text. The
two rankings are merged with reciprocal rank fusion (RRF), which only looks at
ranks, so the two very different score scales never have to be calibrated.

With 16 chunks everything lives in memory: no vector database needed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = ROOT / "data" / "chunks.json"

RRF_K = 60  # standard RRF damping constant

STOPWORDS = set("""
a an and are as at be by for from has have how in is it its of on or that the this to was were what when where which
who whom why will with does do did can should about
""".split())


def load_chunks(path: Path = CHUNKS_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["chunks"]


def index_text(chunk: dict) -> str:
    """What gets indexed: document and section titles carry a lot of the meaning."""
    return f"{chunk['doc_title']}: {chunk['section_title']}\n{chunk['text']}"


def tokenize(text: str) -> list[str]:
    text = re.sub(r"(?<=\d),(?=\d)", "", text.lower())  # "$2,400,000" -> "2400000"
    return [t for t in re.findall(r"\w+", text) if t not in STOPWORDS]


@dataclass
class Hit:
    chunk: dict
    score: float  # RRF score; only meaningful relative to other hits
    bm25_rank: int | None  # 1-based, None when BM25 found no term overlap
    dense_rank: int
    via: str = "search"  # "search", or "related" when pulled in through a related group


class Retriever:
    def __init__(self, chunks: list[dict], model=None, related_groups: list[list[str]] | None = None):
        """`related_groups`: sets of chunk ids that must be retrieved together, e.g. the
        chunks holding each side of a known conflict. Retrieving one pulls in the rest,
        so the answer step always sees every side."""
        self.chunks = chunks
        self.related: dict[str, set[str]] = {}
        for group in related_groups or []:
            for chunk_id in group:
                self.related.setdefault(chunk_id, set()).update(set(group) - {chunk_id})
        self.bm25 = BM25Okapi([tokenize(index_text(c)) for c in chunks])
        if model is None:
            from app.embeddings import OnnxEmbedder
            model = OnnxEmbedder()
        self.model = model
        # e5 models expect "passage: " / "query: " prefixes.
        self.embeddings = self._embed([f"passage: {index_text(c)}" for c in chunks])

    def _embed(self, texts: list[str]) -> np.ndarray:
        return self.model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)

    def bm25_ranking(self, query: str) -> list[int]:
        """Chunk indices by BM25 score, keeping only chunks that share a term with the query.

        An Arabic question scores 0 against every English chunk; ranking those
        zeros would just inject noise into the fusion.
        """
        scores = self.bm25.get_scores(tokenize(query))
        return [i for i in np.argsort(-scores, kind="stable") if scores[i] > 0]

    def dense_ranking(self, query: str) -> list[int]:
        sims = self.embeddings @ self._embed([f"query: {query}"])[0]
        return list(np.argsort(-sims, kind="stable"))

    def search(self, queries: str | list[str], k: int = 4, include_ids: list[str] = ()) -> list[Hit]:
        """Fuse BM25 and dense rankings for one or more phrasings of the same question.

        Passing several queries (e.g. the user's Arabic original plus an English
        rewrite) lets each ranking vote; RRF sums the votes. `include_ids` are added
        after the top k (e.g. the chunks the previous answer cited, for follow-ups).
        """
        if isinstance(queries, str):
            queries = [queries]
        fused = np.zeros(len(self.chunks))
        best_bm25: dict[int, int] = {}
        best_dense: dict[int, int] = {}
        for query in queries:
            for rank, i in enumerate(self.bm25_ranking(query), 1):
                fused[i] += 1 / (RRF_K + rank)
                best_bm25[i] = min(rank, best_bm25.get(i, rank))
            for rank, i in enumerate(self.dense_ranking(query), 1):
                fused[i] += 1 / (RRF_K + rank)
                best_dense[i] = min(rank, best_dense.get(i, rank))
        order = list(np.argsort(-fused, kind="stable"))
        hits = [Hit(self.chunks[i], float(fused[i]), best_bm25.get(i), best_dense[i]) for i in order[:k]]

        found = {h.chunk["id"] for h in hits}
        wanted = set().union(*(self.related.get(h.chunk["id"], set()) for h in hits)) - found
        hits += [Hit(self.chunks[i], float(fused[i]), best_bm25.get(i), best_dense[i], via="related")
                 for i in order if self.chunks[i]["id"] in wanted]

        found |= wanted
        hits += [Hit(self.chunks[i], float(fused[i]), best_bm25.get(i), best_dense[i], via="previous")
                 for i in order if self.chunks[i]["id"] in set(include_ids) - found]
        return hits
