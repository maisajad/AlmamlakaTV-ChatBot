"""Single-turn eval through the full pipeline (router + answer). Calls the Claude API: roughly 3-5 cents per case.

    python -m eval.answer_eval            # all cases
    python -m eval.answer_eval --url https://your-app.onrender.com   # against a deployed instance
    python -m eval.answer_eval ceo q2-marketing   # just these ids
    python -m eval.answer_eval --recheck          # re-apply the checks to the saved answers (no API calls)
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from pathlib import Path

import yaml

from app.language import detect_language, script_language
from app.pipeline import ChatBot
from eval.remote import RemoteBot

CASES_PATH = Path(__file__).with_name("answer_cases.yaml")
RESULTS_PATH = Path(__file__).with_name("answer_results.json")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def norm(text: str) -> str:
    text = text.translate(ARABIC_DIGITS).lower()
    return re.sub(r"(?<=\d)[,٬  ](?=\d{3})", "", text)  # 2,600,000 / 2٬600٬000 -> 2600000


def check(case: dict, result: dict) -> list[str]:
    problems = []
    if result["status"] not in case["status"]:
        problems.append(f"status {result['status']!r}, expected one of {case['status']}")
        return problems
    if result["status"] != "answered":
        return problems
    answer = norm(result["answer"])
    for alternatives in case.get("includes", []):
        if not any(norm(alt) in answer for alt in alternatives):
            problems.append(f"answer lacks any of {alternatives}")
    for banned in case.get("excludes", []):
        if norm(banned) in answer:
            problems.append(f"answer contains {banned!r}")
    cited = {c["chunk_id"] for c in result["citations"]}
    for chunk_id in case.get("cites", []):
        if chunk_id not in cited:
            problems.append(f"missing citation {chunk_id}")
    if case.get("conflict") and not result["conflicts"]:
        problems.append("no conflict flagged")
    expected_lang = detect_language(case["q"])
    if script_language(result["answer"]) != expected_lang:
        problems.append("answer is not in the question's language")
    for conflict in result["conflicts"]:
        text = " ".join([conflict["topic"]] + [cl["statement"] for cl in conflict["claims"]])
        if script_language(text) != expected_lang:
            problems.append("conflict callout is not in the question's language")
            break
    return problems


def recheck() -> int:
    """After changing a check (not the bot), re-score the answers already recorded."""
    cases = {c["id"]: c for c in yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))}
    records = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    for r in records:
        r["problems"] = check(cases[r["id"]], r["result"])
        print(f"{'PASS' if not r['problems'] else 'FAIL'} {r['id']:<28} {'; '.join(r['problems'])}")
    RESULTS_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failed = sum(bool(r["problems"]) for r in records)
    print(f"\n{len(records) - failed}/{len(records)} passed (rechecked, no API calls)")
    return 1 if failed else 0


def main(args: list[str]) -> int:
    if "--recheck" in args:
        return recheck()
    url = args[args.index("--url") + 1] if "--url" in args else None
    ids = [a for a in args if a != "--url" and a != url]
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    cases = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
    if ids:
        cases = [c for c in cases if c["id"] in ids]
    bot = RemoteBot(url) if url else ChatBot()
    print(f"target: {url or 'in-process'}")

    records, failures = [], 0
    for case in cases:
        start = time.monotonic()
        result = bot.chat(None, case["q"])  # fresh session per case
        problems = check(case, result)
        failures += bool(problems)
        records.append({"id": case["id"], "q": case["q"], "problems": problems, "result": result})
        print(f"{'PASS' if not problems else 'FAIL'} {case['id']:<28} {result['status']:<17} "
              f"{time.monotonic() - start:4.1f}s  {'; '.join(problems)}")

    RESULTS_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{len(cases) - failures}/{len(cases)} passed. Full answers: {RESULTS_PATH.name}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
