"""Check generated content against its fact sheet. Pure functions, no I/O.

A result passes only when: the shape and counts are right, every number is in the fact
sheet (within 0.5 percent), every capitalised name comes from the allowlist, and no
speculative or superlative claim appears.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.content.facts import FactSheet
from app.services.content.numbers import extract_amounts, matches

SUMMARY_WORDS = (40, 60)
META_MAX_CHARS = 155
COUNTS = {
    "locality": {"highlights": (3, 5), "faqs": (4, 6)},
    "property": {"pros": (2, 4), "cons": (1, 3)},
    "digest": {"sections": (2, 4)},
}

BANNED = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bguarantee[sd]?\b", r"\bassured\b", r"\brisk[- ]free\b", r"\bbest\b", r"\bnumber one\b",
        r"\bno\.?\s?1\b", r"#1", r"\bsure[- ]?shot\b", r"\bcan'?t go wrong\b",
        r"\bwill\s+(?:\w+\s+){0,2}(?:appreciate|rise|increase in value|go up|double|gain value)\b",
        r"\b(?:high|good|strong|great|assured)\s+returns?\b", r"\breturns? on investment\b",
        r"\bonce[- ]in[- ]a[- ]lifetime\b", r"\bundervalued\b", r"\bbooming\b",
        r"गारंटी", r"पक्का\s+मुनाफ", r"सबसे\s+(?:अच्छ|बेहतर)", r"जोखिम[- ]?मुक्त",
        r"(?:कीमतें|दाम|भाव)\s+बढ़ेंगे?", r"निश्चित\s+(?:रूप\s+से\s+)?(?:मुनाफ|रिटर्न)",
    )
]  # fmt: skip

# Capitalised words that are not names. Months appear when a writer states the data date.
_COMMON = {
    "i", "a", "an", "the", "faq", "emi", "gst", "bhk", "rera", "ncr", "nh", "sq", "ft", "yd",
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday", "rs", "inr",
}  # fmt: skip
_CAP_WORD = re.compile(r"\b[A-Z][A-Za-z'’]*\b")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?।])\s+|\n+")
_WORD = re.compile(r"[\w'’]+", re.UNICODE)


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _texts(output: dict[str, Any]) -> list[tuple[str, str]]:
    """Flatten the output into (path, text) pairs."""
    pairs: list[tuple[str, str]] = []
    for key, value in output.items():
        if isinstance(value, str):
            pairs.append((key, value))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, str):
                    pairs.append((f"{key}[{i}]", item))
                elif isinstance(item, dict):
                    pairs += [(f"{key}[{i}].{k}", v) for k, v in item.items() if isinstance(v, str)]
    return pairs


def word_count(text: str) -> int:
    return len(text.split())


def _mask_names(text: str, names: set[str]) -> str:
    for name in sorted(names, key=len, reverse=True):
        if name:
            text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)
    return text


def check_numbers(text: str, sheet: FactSheet, allowed: set[float]) -> list[str]:
    masked = _mask_names(text, sheet.allowed_names())
    return [
        f"number '{a.text}' is not in the facts"
        for a in extract_amounts(masked)
        if not matches(a.value, allowed)
    ]


def check_names(text: str, allowed_words: set[str]) -> list[str]:
    bad: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(text):
        words = _CAP_WORD.findall(sentence)
        first = _WORD.match(sentence.strip())
        for i, word in enumerate(words):
            if i == 0 and first and first.group(0) == word:
                continue  # sentence start: capital letter is grammar, not a name
            if word.lower() not in allowed_words and word.lower() not in _COMMON:
                bad.append(word)
    return [f"name '{w}' is not in the facts" for w in dict.fromkeys(bad)]


def validate(output: dict[str, Any], sheet: FactSheet, locale: str) -> ValidationResult:
    result = ValidationResult()
    kind = sheet.entity_type
    required = {"summary", "meta_description", *COUNTS[kind]} | ({"who_it_suits"} if kind == "property" else set())
    missing = sorted(required - output.keys())
    if missing:
        result.errors.append(f"missing fields: {', '.join(missing)}")
        return result

    summary = output["summary"]
    if not isinstance(summary, str) or not SUMMARY_WORDS[0] <= word_count(summary) <= SUMMARY_WORDS[1]:
        got = word_count(summary) if isinstance(summary, str) else 0
        result.errors.append(f"summary has {got} words, need {SUMMARY_WORDS[0]} to {SUMMARY_WORDS[1]}")
    meta = output["meta_description"]
    if not isinstance(meta, str) or not meta.strip() or len(meta) > META_MAX_CHARS:
        result.errors.append(f"meta_description must be 1 to {META_MAX_CHARS} characters")
    for key, (lo, hi) in COUNTS[kind].items():
        items = output[key]
        if not isinstance(items, list) or not lo <= len(items) <= hi:
            result.errors.append(f"{key} needs {lo} to {hi} items")
        elif key == "faqs" and not all(
            isinstance(x, dict) and str(x.get("question", "")).strip() and str(x.get("answer", "")).strip()
            for x in items
        ):
            result.errors.append("every FAQ needs a question and an answer")
        elif key == "sections" and not all(
            isinstance(x, dict) and str(x.get("heading", "")).strip() and str(x.get("body", "")).strip()
            for x in items
        ):
            result.errors.append("every section needs a heading and a body")
    if kind == "property" and not str(output["who_it_suits"]).strip():
        result.errors.append("who_it_suits is empty")
    if result.errors:
        return result

    allowed = sheet.allowed_numbers()
    allowed_words = {w.lower() for n in sheet.allowed_names() for w in _WORD.findall(n)}
    for path, text in _texts(output):
        for pattern in BANNED:
            if pattern.search(text):
                result.errors.append(f"{path}: banned claim '{pattern.search(text).group(0)}'")  # type: ignore[union-attr]
        result.errors += [f"{path}: {e}" for e in check_numbers(text, sheet, allowed)]
        result.errors += [f"{path}: {e}" for e in check_names(text, allowed_words)]
    return result
