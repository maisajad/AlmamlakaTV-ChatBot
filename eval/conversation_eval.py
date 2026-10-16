"""Multi-turn eval through the full pipeline. Calls the Claude API: roughly 4-6 cents per turn.

    python -m eval.conversation_eval [conversation ids...] [--url https://your-app.onrender.com]
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import yaml

from app.pipeline import ChatBot
from eval.remote import RemoteBot
from eval.answer_eval import check

CASES_PATH = Path(__file__).with_name("conversation_cases.yaml")
RESULTS_PATH = Path(__file__).with_name("conversation_results.json")


def main(args: list[str]) -> int:
    url = args[args.index("--url") + 1] if "--url" in args else None
    ids = [a for a in args if a != "--url" and a != url]
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    conversations = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
    if ids:
        conversations = [c for c in conversations if c["id"] in ids]
    bot = RemoteBot(url) if url else ChatBot()
    print(f"target: {url or 'in-process'}")

    records, failed_turns, total_turns = [], 0, 0
    for convo in conversations:
        session_id, failed = None, False
        print(f"\n{convo['id']}")
        for n, turn in enumerate(convo["turns"], 1):
            start = time.monotonic()
            result = bot.chat(session_id, turn["q"])
            session_id = result["session_id"]
            problems = check(turn, result)
            failed |= bool(problems)
            failed_turns += bool(problems)
            total_turns += 1
            records.append({"conversation": convo["id"], "turn": n, "q": turn["q"], "problems": problems,
                            "result": result})
            print(f"  {'PASS' if not problems else 'FAIL'} {n}. {turn['q'][:55]:<55} {result['status']:<16} "
                  f"{time.monotonic() - start:4.1f}s  {'; '.join(problems)}")
            print(f"       -> {result.get('intent')}: {result.get('standalone_query')!r}")

    RESULTS_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{total_turns - failed_turns}/{total_turns} turns passed. Full answers: {RESULTS_PATH.name}")
    return 1 if failed_turns else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
