"""Retrieval eval: recall@k for BM25, dense and hybrid, in English and Arabic.

    python -m eval.retrieval_eval [--k 4]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from app.retrieval import Retriever, load_chunks

CASES_PATH = Path(__file__).with_name("retrieval_cases.yaml")
LANGUAGES = ("en", "ar")
METHODS = ("bm25", "dense", "hybrid")


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def top_ids(retriever: Retriever, method: str, query: str, k: int) -> list[str]:
    if method == "hybrid":
        return [hit.chunk["id"] for hit in retriever.search(query, k)]
    ranking = retriever.bm25_ranking(query) if method == "bm25" else retriever.dense_ranking(query)
    return [retriever.chunks[i]["id"] for i in ranking[:k]]


def passes(case: dict, ids: list[str]) -> bool:
    return all(c in ids for c in case.get("all_of", [])) and (
        not case.get("any_of") or any(c in ids for c in case["any_of"]))


def run(retriever: Retriever, cases: list[dict], k: int) -> dict:
    """Returns {(method, lang): [(case, ids, passed), ...]}."""
    return {(method, lang): [(case, ids := top_ids(retriever, method, case[lang], k), passes(case, ids))
                             for case in cases]
            for method in METHODS for lang in LANGUAGES}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=4)
    args = parser.parse_args()

    cases = load_cases()
    results = run(Retriever(load_chunks()), cases, args.k)

    print(f"recall@{args.k} over {len(cases)} questions\n")
    print(f"{'method':<8}" + "".join(f"{lang:>10}" for lang in LANGUAGES))
    for method in METHODS:
        cells = [sum(p for *_, p in results[method, lang]) for lang in LANGUAGES]
        print(f"{method:<8}" + "".join(f"{n:>6}/{len(cases):<3}" for n in cells))

    for lang in LANGUAGES:
        for case, ids, ok in results["hybrid", lang]:
            if not ok:
                want = case.get("all_of", []) + case.get("any_of", [])
                print(f"\nFAIL hybrid/{lang} {case['id']}: {case[lang]}\n  want {want}\n  got  {ids}")


if __name__ == "__main__":
    main()
