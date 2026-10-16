"""Code-side checks on the model's answer. The model cannot cite what it was not given,
and every quote it offers as evidence must really be in the chunk it points to."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

MIN_QUOTE_CHARS = 8
QUOTE_MATCH_THRESHOLD = 90  # rapidfuzz partial_ratio, 0-100; tolerates small whitespace/punctuation drift
MARKER = re.compile(r"\[(\d+)\]")


def normalize(text: str) -> str:
    text = text.lower().translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"}))
    text = re.sub(r"[|*#`]", " ", text)  # Markdown table pipes and emphasis
    return re.sub(r"\s+", " ", text).strip()


def numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+", re.sub(r"(?<=\d),(?=\d)", "", text)))


def quote_supported(quote: str, chunk_text: str) -> bool:
    """Fuzzy match for wording, exact match for numbers: '$3,100,000' is only two
    characters away from '$2,600,000', and figures are what must never drift."""
    q, t = normalize(quote), normalize(chunk_text)
    if len(q) < MIN_QUOTE_CHARS or not numbers(q) <= numbers(t):
        return False
    return q in t or fuzz.partial_ratio(q, t) >= QUOTE_MATCH_THRESHOLD


@dataclass
class Verdict:
    problems: list[str] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)  # only the well-formed ones

    @property
    def ok(self) -> bool:
        return not self.problems


def verify(raw: dict, allowed: dict[str, dict]) -> Verdict:
    """`allowed` maps chunk id -> chunk for exactly the chunks that were in the prompt."""
    verdict = Verdict()
    if raw["status"] != "answered":
        return verdict

    citations = raw["citations"]
    if not citations:
        verdict.problems.append("status is answered but there are no citations")
    for n, citation in enumerate(citations, 1):
        chunk = allowed.get(citation["chunk_id"])
        if chunk is None:
            verdict.problems.append(f"citation [{n}] uses chunk id {citation['chunk_id']!r}, which was not provided")
        elif not quote_supported(citation["quote"], chunk["text"]):
            verdict.problems.append(f"citation [{n}] quote {citation['quote']!r} is not verbatim text from {citation['chunk_id']}")

    for marker in {int(m) for m in MARKER.findall(raw["answer"])}:
        if not 1 <= marker <= len(citations):
            verdict.problems.append(f"answer uses marker [{marker}] but there are {len(citations)} citations")
    if citations and not MARKER.search(raw["answer"]):
        verdict.problems.append("answer has no [n] citation markers")

    verdict.conflicts = [c for c in raw["conflicts"]
                         if len(c["claims"]) >= 2 and all(cl["chunk_id"] in allowed for cl in c["claims"])]
    return verdict
