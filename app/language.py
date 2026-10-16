"""Language detection and the fixed replies the bot gives in each language."""

from __future__ import annotations

import re

ARABIC_LETTER = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
LATIN_LETTER = re.compile(r"[A-Za-z]")

NAMES = {"en": "English", "ar": "Arabic"}

REPLIES = {
    "not_in_documents": {
        "en": "I don't have that information. The project documents I can draw on don't cover it.",
        "ar": "لا تتوفر لديّ هذه المعلومة، فهي غير مذكورة في وثائق المشروع المتاحة لي.",
    },
    "out_of_scope": {
        "en": "I can only answer questions about Almamlaka TV's Digital Expansion Initiative, based on its "
              "project documents. Feel free to ask about its goals, budget, timeline, team or policies.",
        "ar": "يمكنني الإجابة فقط عن الأسئلة المتعلقة بمبادرة التوسع الرقمي لقناة المملكة، استنادًا إلى وثائق "
              "المشروع. يمكنك السؤال عن أهدافها أو ميزانيتها أو جدولها الزمني أو فريقها أو سياساتها.",
    },
    "greeting": {
        "en": "Hello! I'm the Almamlaka TV assistant. Ask me anything about the Digital Expansion Initiative: "
              "its goals, budget, timeline, team or policies.",
        "ar": "أهلًا بك! أنا مساعد قناة المملكة. اسألني عن أي شيء يخص مبادرة التوسع الرقمي: أهدافها أو ميزانيتها "
              "أو جدولها الزمني أو فريقها أو سياساتها.",
    },
    "too_long": {
        "en": "That message is too long. Please keep questions under {limit} characters.",
        "ar": "الرسالة طويلة جدًا. يُرجى ألا يتجاوز السؤال {limit} حرف.",
    },
    "rate_limited": {
        "en": "You're sending messages too quickly. Please wait a moment and try again.",
        "ar": "أنت ترسل الرسائل بسرعة كبيرة. يُرجى الانتظار قليلًا ثم المحاولة مجددًا.",
    },
    "busy": {
        "en": "The assistant is receiving a lot of questions right now. Please try again in a little while.",
        "ar": "يتلقى المساعد عددًا كبيرًا من الأسئلة حاليًا. يُرجى المحاولة مرة أخرى بعد قليل.",
    },
    "error": {
        "en": "Sorry, something went wrong while preparing the answer. Please try again.",
        "ar": "عذرًا، حدث خطأ أثناء إعداد الإجابة. يُرجى المحاولة مرة أخرى.",
    },
}


def script_language(text: str, default: str = "en") -> str:
    """Language by script alone. For checking the model's own output, where Arabic must mean
    Arabic script: "$2.6M" or "Q2" in an English answer must never read as Arabizi."""
    arabic = len(ARABIC_LETTER.findall(text))
    latin = len(LATIN_LETTER.findall(text))
    if not arabic and not latin:
        return default
    return "ar" if arabic / (arabic + latin) >= 0.3 else "en"


def detect_language(text: str, default: str = "en") -> str:
    """'ar' when Arabic letters make up at least 30% of the letters, 'en' otherwise.
    Text with no letters at all ("2027?") gets `default`, e.g. the conversation's language."""
    arabic = len(ARABIC_LETTER.findall(text))
    latin = len(LATIN_LETTER.findall(text))
    if not arabic and not latin:
        return default
    if arabic / (arabic + latin) >= 0.3:
        return "ar"
    return "ar" if is_arabizi(text) else "en"


# Arabizi: Arabic in Latin letters, with digits for sounds Latin lacks (3 = ع, 7 = ح, 2 = ء, 5 = خ ...).
# A digit-word mixes letters with one of those digits, but isn't shaped like a unit or label
# (Q2, H1, 6M, 3D, 4K, 2nd, 5th).
UNIT_LIKE = re.compile(r"[a-z]\d+|\d+[a-z]{1,2}")


def arabizi_digit_words(text: str) -> int:
    count = 0
    for token in re.findall(r"[a-z0-9']+", text.lower()):
        letters = sum(c.isalpha() for c in token)
        if letters >= 2 and re.search(r"[235679]", token) and not UNIT_LIKE.fullmatch(token):
            count += 1
    return count
ARABIZI_WORDS = {
    # common Jordanian / Levantine words, spelled the ways people type them
    "shu", "sho", "shou", "eesh", "esh", "ish", "kif", "keef", "kaif", "kaifak", "kifak", "emta", "imta", "eemta",
    "meen", "mnein", "wen", "wein", "ween", "leish", "lesh", "laish", "ad", "adde", "addesh", "adesh", "adeish",
    "ya3ni", "yaani", "yani", "hal", "hay", "hada", "hadi", "hdol", "fi", "fee", "ma", "mish", "msh", "bdi", "baddi",
    "badi", "3ndi", "3ndkom", "el", "il", "w", "wala", "walla", "yalla", "tayeb", "tayyeb", "mashi", "kteer", "ktir",
    "shway", "shwai", "mazboot", "ahlan", "marhaba", "mar7aba", "shukran", "habibi", "inshallah", "mashallah",
    "masroo3", "mashroo3", "mashrou3", "meezanie", "mizaniye", "mizanie", "itlaq", "el2itla2", "fareeq", "fari2",
}
ENGLISH_HINTS = {"the", "is", "are", "what", "who", "when", "how", "which", "does", "of", "and", "to", "in", "for"}


def is_arabizi(text: str) -> bool:
    """Latin-script text that reads as Arabic: digit-letter words like 'ma3' or '7aga', or
    several dialect words, and clearly more of those than English function words."""
    words = re.findall(r"[A-Za-z0-9']+", text.lower())
    if not words:
        return False
    digit_words = arabizi_digit_words(text)
    dialect_words = sum(w in ARABIZI_WORDS for w in words)
    english = sum(w in ENGLISH_HINTS for w in words)
    score = 2 * digit_words + dialect_words
    return score >= 2 and score > 2 * english


def reply(kind: str, language: str, **values) -> str:
    return REPLIES[kind][language].format(**values)
