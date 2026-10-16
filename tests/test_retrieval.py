import zlib

import numpy as np
import pytest

from app.retrieval import Retriever, load_chunks, tokenize
from eval.retrieval_eval import LANGUAGES, load_cases, run


class HashEmbedder:
    """Stand-in for the embedding model: fast, deterministic, meaningless vectors."""

    def encode(self, texts, normalize_embeddings=True, convert_to_numpy=True):
        # zlib.crc32, not hash(): str hashes are salted per process, which made tests flaky.
        vecs = np.array([np.random.default_rng(zlib.crc32(t.encode())).normal(size=8) for t in texts])
        return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


@pytest.fixture(scope="module")
def fake_retriever():
    return Retriever(load_chunks(), model=HashEmbedder())


def test_tokenize_normalizes_money_and_drops_stopwords():
    assert tokenize("What is the Total Budget: $2,400,000?") == ["total", "budget", "2400000"]


def test_bm25_ignores_chunks_with_no_shared_terms(fake_retriever):
    assert fake_retriever.bm25_ranking("ما هي الميزانية الإجمالية؟") == []


def test_bm25_finds_exact_figures(fake_retriever):
    top = fake_retriever.chunks[fake_retriever.bm25_ranking("budget changes above $50,000")[0]]
    assert top["id"] == "team_governance#2"


def test_search_returns_k_distinct_chunks(fake_retriever):
    hits = fake_retriever.search(["When is the launch?", "متى الإطلاق؟"], k=4)
    assert len({h.chunk["id"] for h in hits}) == 4
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


class BM25Retriever(Retriever):
    """Dense ranking mirrors BM25, so fused results are predictable."""

    def dense_ranking(self, query):
        ranked = self.bm25_ranking(query)
        return ranked + [i for i in range(len(self.chunks)) if i not in ranked]


def test_related_group_pulls_in_the_other_side():
    group = ["project_overview#3", "budget_timeline#2"]
    retriever = BM25Retriever(load_chunks(), model=HashEmbedder(), related_groups=[group])
    hits = retriever.search("budget changes above $50,000", k=1)
    assert [h.chunk["id"] for h in hits][0] == "team_governance#2"  # not in the group: nothing added
    assert len(hits) == 1

    hits = retriever.search("revision by the Finance Committee in December 2026", k=1)
    assert [(h.chunk["id"], h.via) for h in hits] == [("budget_timeline#2", "search"), ("project_overview#3", "related")]


@pytest.mark.slow
def test_hybrid_recall_at_4_is_perfect_in_both_languages():
    """Loads the real embedding model (downloads it on first run)."""
    results = run(Retriever(load_chunks()), load_cases(), k=4)
    for lang in LANGUAGES:
        failed = [case["id"] for case, _, ok in results["hybrid", lang] if not ok]
        assert not failed, f"{lang}: {failed}"
