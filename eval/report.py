"""Build static/quality-report.json (the /quality page) from the latest eval results.

Run the evals first; this only reads their output (and recomputes the free retrieval eval):

    python -m eval.answer_eval --url https://your-app.onrender.com
    python -m eval.conversation_eval --url https://your-app.onrender.com
    python -m eval.report --target "live Render deployment"
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

import yaml

from app.llm import MODEL
from app.retrieval import ROOT
from eval import answer_eval, conversation_eval, retrieval_eval

OUT = ROOT / "static" / "quality-report.json"
CATEGORY_ORDER = ["facts", "conflicts", "out_of_scope", "injection", "dialect"]
MAX_ANSWER_CHARS = 1600


def label(c: dict) -> str:
    section = f"Section {c['section']}: " if c.get("section") else ""
    return f"{c['doc_title']} · p. {', '.join(map(str, c['pages']))} · {section}{c['section_title']}"


def view(result: dict) -> dict:
    return {
        "status": result["status"],
        "language": result["language"],
        "answer": result["answer"][:MAX_ANSWER_CHARS],
        "citations": [{"n": c["n"], "label": label(c), "quote": c["quote"]} for c in result["citations"]],
        "conflicts": [c["topic"] for c in result["conflicts"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="local instance")
    args = parser.parse_args()

    categories = {c["id"]: c.get("category", "other")
                  for c in yaml.safe_load(answer_eval.CASES_PATH.read_text(encoding="utf-8"))}
    answers = json.loads(answer_eval.RESULTS_PATH.read_text(encoding="utf-8"))
    turns = json.loads(conversation_eval.RESULTS_PATH.read_text(encoding="utf-8"))

    cases = [{"id": r["id"], "category": categories.get(r["id"], "other"), "question": r["q"],
              "passed": not r["problems"], "problems": r["problems"], **view(r["result"])} for r in answers]
    conversations: dict[str, dict] = {}
    for r in turns:
        convo = conversations.setdefault(r["conversation"], {"id": r["conversation"], "turns": []})
        convo["turns"].append({"question": r["q"], "passed": not r["problems"], "problems": r["problems"],
                               **view(r["result"])})
    for convo in conversations.values():
        convo["passed"] = all(t["passed"] for t in convo["turns"])

    summary = {cat: {"passed": sum(c["passed"] for c in cases if c["category"] == cat),
                     "total": sum(c["category"] == cat for c in cases)} for cat in CATEGORY_ORDER}
    summary["follow_ups"] = {"passed": sum(t["passed"] for c in conversations.values() for t in c["turns"]),
                             "total": sum(len(c["turns"]) for c in conversations.values())}

    retrieval_cases = retrieval_eval.load_cases()
    from app.answer import load_conflicts
    from app.retrieval import Retriever, load_chunks
    retriever = Retriever(load_chunks(), related_groups=[[cl["chunk_id"] for cl in c["claims"]] for c in load_conflicts()])
    results = retrieval_eval.run(retriever, retrieval_cases, k=4)
    retrieval = {lang: {"passed": sum(ok for *_, ok in results["hybrid", lang]), "total": len(retrieval_cases)}
                 for lang in retrieval_eval.LANGUAGES}

    report = {
        "generated": datetime.date.today().isoformat(),
        "model": MODEL,
        "target": args.target,
        "summary": summary,
        "retrieval": retrieval,
        "cases": sorted(cases, key=lambda c: (CATEGORY_ORDER.index(c["category"]) if c["category"] in CATEGORY_ORDER else 99)),
        "conversations": list(conversations.values()),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    totals = [v for k, v in summary.items()]
    print(f"{sum(t['passed'] for t in totals)}/{sum(t['total'] for t in totals)} passed -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
