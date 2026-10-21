"""Check generated content against its fact sheet. Pure functions, no I/O.

A result passes only when: the shape, types and counts are right, every number is in the
fact sheet (same kind, within 0.5 percent for large values), every capitalised name comes
from the allowlist, and no speculative or superlative claim appears.

Limits, by design: a name written in Devanagari cannot be checked, so the prompt asks for
names in Latin script as listed. A capitalised word that starts a sentence is checked only
when a second capitalised word follows it (a project or company name) or it is a known
city. A claim made in ordinary words with no number or name is not detected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.content.facts import FactSheet
from app.services.content.numbers import Allowed, extract_amounts, matches

SUMMARY_WORDS = (40, 60)
META_MAX_CHARS = 155
COUNTS = {
    "locality": {"highlights": (3, 5), "faqs": (4, 6)},
    "property": {"pros": (2, 4), "cons": (1, 3)},
    "digest": {"sections": (1, 4)},
}

BANNED = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bguarantee[sd]?\b", r"\bassured\b", r"\brisk[- ]free\b", r"\bbest\b", r"\bnumber one\b",
        r"\bno\.?\s?1\b", r"#1", r"\bsure[- ]?shot\b", r"\bcan'?t go wrong\b",
        r"\bwill\s+(?:\w+\s+){0,2}(?:appreciate|rise|increase in value|go up|double|gain value)\b",
        r"\b(?:high|good|strong|great|assured)\s+returns?\b", r"\breturns? on investment\b",
        r"\bonce[- ]in[- ]a[- ]lifetime\b", r"\bundervalued\b", r"\bbooming\b",
        r"\b(?:finest|safest|unmatched|unbeatable|unparalleled|premier|top[- ]rated|dream home)\b",
        r"\bmost (?:popular|sought[- ]after|prestigious)\b",
        r"गारंटी", r"पक्का\s+मुनाफ", r"सबसे\s+(?:अच्छ|बेहतर)", r"जोखिम[- ]?मुक्त",
        r"(?:कीमतें|दाम|भाव)\s+बढ़ेंगे?", r"निश्चित\s+(?:रूप\s+से\s+)?(?:मुनाफ|रिटर्न)",
    )
]  # fmt: skip

# Capitalised words that are not names. Months appear when a writer states the data date.
_COMMON = {
    "i", "a", "an", "the", "faq", "emi", "gst", "bhk", "rera", "ncr", "nh", "sq", "ft", "yd",
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday", "rs", "inr", "lakh", "lakhs", "crore", "crores",
}  # fmt: skip
# Cities a model may reach for. Checked even at the start of a sentence.
_CITIES = {
    "mumbai", "pune", "bengaluru", "bangalore", "hyderabad", "chennai", "kolkata", "ahmedabad",
    "noida", "ghaziabad", "faridabad", "jaipur", "lucknow", "chandigarh", "indore", "goa", "dubai",
}  # fmt: skip
_CAP_WORD = re.compile(r"\b[A-Z][A-Za-z'’]*\b")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?।])\s+|\n+")
_WORD = re.compile(r"[\w'’]+", re.UNICODE)
_POSSESSIVE = re.compile(r"['’]s$")


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


def check_numbers(text: str, sheet: FactSheet, allowed: Allowed) -> list[str]:
    masked = _mask_names(text, sheet.allowed_names())
    return [
        f"number '{a.text}' is not in the facts"
        for a in extract_amounts(masked)
        if not matches(a, allowed)
    ]


def check_names(text: str, allowed_words: set[str], label_words: frozenset[str] = frozenset()) -> list[str]:
    bad: list[str] = []

    def known(word: str) -> bool:
        w = _POSSESSIVE.sub("", word).lower()
        # Names must match exactly. A plural is accepted only for the plain words of fact labels.
        return w in allowed_words or w in _COMMON or (w.endswith("s") and w[:-1] in label_words)

    for sentence in _SENTENCE_SPLIT.split(text):
        sentence = sentence.strip()
        found = list(_CAP_WORD.finditer(sentence))
        for m in found:
            if known(m.group(0)):
                continue
            if m.start() == 0:
                # The first word is capitalised by grammar. It is a name only when another
                # unknown capitalised word follows it directly ("Sobha City"), or it is a known
                # city. "Weekly Gurugram" passes: the second word is an allowed name.
                follows = (
                    len(found) > 1
                    and sentence[m.end() : found[1].start()].strip() == ""
                    and not known(found[1].group(0))
                )
                if not follows and _POSSESSIVE.sub("", m.group(0)).lower() not in _CITIES:
                    continue
            bad.append(_POSSESSIVE.sub("", m.group(0)))
    return [f"name '{w}' is not in the facts" for w in dict.fromkeys(bad)]


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _shape_errors(output: dict[str, Any], kind: str) -> list[str]:
    errors: list[str] = []
    required = {"summary", "meta_description", *COUNTS[kind]} | ({"who_it_suits"} if kind == "property" else set())
    missing = sorted(required - output.keys())
    if missing:
        return [f"missing fields: {', '.join(missing)}"]

    summary = output["summary"]
    if not isinstance(summary, str) or not SUMMARY_WORDS[0] <= word_count(summary) <= SUMMARY_WORDS[1]:
        got = word_count(summary) if isinstance(summary, str) else 0
        errors.append(f"summary has {got} words, need {SUMMARY_WORDS[0]} to {SUMMARY_WORDS[1]}")
    meta = output["meta_description"]
    if not _is_text(meta) or len(meta) > META_MAX_CHARS:
        errors.append(f"meta_description must be 1 to {META_MAX_CHARS} characters")
    if kind == "property" and not _is_text(output["who_it_suits"]):
        errors.append("who_it_suits must be text")
    pair_keys = {"faqs": ("question", "answer"), "sections": ("heading", "body")}
    for key, (lo, hi) in COUNTS[kind].items():
        items = output[key]
        if not isinstance(items, list) or not lo <= len(items) <= hi:
            errors.append(f"{key} needs {lo} to {hi} items")
        elif key in pair_keys:
            if not all(isinstance(x, dict) and all(_is_text(x.get(k)) for k in pair_keys[key]) for x in items):
                errors.append(f"every item in {key} needs {' and '.join(pair_keys[key])} as text")
        elif not all(_is_text(x) for x in items):
            errors.append(f"every item in {key} must be text")
    return errors


def validate(output: dict[str, Any], sheet: FactSheet, locale: str) -> ValidationResult:
    result = ValidationResult(_shape_errors(output, sheet.entity_type))
    if result.errors:
        return result

    allowed = sheet.allowed_numbers()
    # Names, plus the plain words of the fact labels ("Government", "Circle", "Nearby"): a writer
    # may capitalise those mid-sentence, and they are not names.
    label_words = frozenset(w.lower() for f in sheet.facts for w in _WORD.findall(f.label))
    allowed_words = {w.lower() for n in sheet.allowed_names() for w in _WORD.findall(n)} | label_words
    for path, text in _texts(output):
        for pattern in BANNED:
            found = pattern.search(text)
            if found:
                result.errors.append(f"{path}: banned claim '{found.group(0)}'")
        result.errors += [f"{path}: {e}" for e in check_numbers(text, sheet, allowed)]
        result.errors += [f"{path}: {e}" for e in check_names(text, allowed_words, label_words)]
    return result
