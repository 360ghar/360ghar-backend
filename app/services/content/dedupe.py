"""Near-duplicate detection between sibling entities (5-word shingle Jaccard)."""

from __future__ import annotations

import re

SHINGLE = 5
REJECT_AT = 0.5
REVIEW_AT = 0.35

_WORD = re.compile(r"[\w'’]+", re.UNICODE)


def shingles(text: str) -> set[tuple[str, ...]]:
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < SHINGLE:
        return {tuple(words)} if words else set()
    return {tuple(words[i : i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}


def jaccard(a: set[tuple[str, ...]], b: set[tuple[str, ...]]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def max_similarity(text: str, siblings: dict[str, str]) -> tuple[float, str | None]:
    """Highest Jaccard score of ``text`` against sibling texts, and which sibling."""
    mine = shingles(text)
    best, best_slug = 0.0, None
    for slug, other in siblings.items():
        score = jaccard(mine, shingles(other))
        if score > best:
            best, best_slug = score, slug
    return best, best_slug


def decision(score: float) -> str:
    """'reject' at 0.5 and above, 'review' at 0.35 and above, otherwise 'ok'."""
    if score >= REJECT_AT:
        return "reject"
    return "review" if score >= REVIEW_AT else "ok"


def content_text(body: dict[str, object]) -> str:
    """The comparable text of a content body: summary, bullets and FAQ answers."""
    parts: list[str] = [str(body.get("summary", ""))]
    for key in ("highlights", "pros", "cons"):
        parts += [str(x) for x in body.get(key, []) or []]  # type: ignore[attr-defined]
    parts += [str(f.get("answer", "")) for f in body.get("faqs", []) or []]  # type: ignore[attr-defined]
    return " ".join(parts)
