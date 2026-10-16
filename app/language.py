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


def detect_language(text: str, default: str = "en") -> str:
    """'ar' when Arabic letters make up at least 30% of the letters, 'en' otherwise.
    Text with no letters at all ("2027?") gets `default`, e.g. the conversation's language."""
    arabic = len(ARABIC_LETTER.findall(text))
    latin = len(LATIN_LETTER.findall(text))
    if not arabic and not latin:
        return default
    return "ar" if arabic / (arabic + latin) >= 0.3 else "en"


def reply(kind: str, language: str, **values) -> str:
    return REPLIES[kind][language].format(**values)
