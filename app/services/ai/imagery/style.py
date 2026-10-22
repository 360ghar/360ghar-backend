"""The one house style for generated art, and the idempotent key for each image.

Change HOUSE_STYLE or STYLE_VERSION only together: the version is part of every key, so a
new version regenerates all art on the next nightly run.
"""

from __future__ import annotations

import hashlib

STYLE_VERSION = "v1"

HOUSE_STYLE = (
    "A handmade paper diorama, layered cut paper and card in a shallow miniature stage, "
    "soft directional studio light from the upper left, tactile paper grain, muted natural "
    "palette with one warm accent, gentle depth of field, calm and uncluttered composition "
    "with open space in the lower third. No text, no letters, no numbers, no logos, "
    "no signs, no watermarks, no people, no faces."
)

SUBJECT_TYPES = ("city", "locality", "property", "blog")

# Each ratio and size pair is a separate image. OG art is 16:9 at 1K, hero art 16:9 at 2K.
OG_RATIO, OG_SIZE = "16:9", "1K"
HERO_RATIO, HERO_SIZE = "16:9", "2K"


def image_key(subject_type: str, slug: str, ratio: str, size: str) -> str:
    """sha256 of style version, subject, ratio and size. Same inputs always give the same key."""
    raw = "|".join((STYLE_VERSION, subject_type, slug, ratio, size))
    return hashlib.sha256(raw.encode()).hexdigest()


def build_prompt(subject_type: str, name: str, city: str | None = None) -> str:
    """The prompt for one subject. ``name`` is a place or topic, never user-written free text."""
    scenes = {
        "city": f"the skyline and streets of {name}, India, as a paper city",
        "locality": f"a residential neighbourhood in {name}{', ' + city if city else ''}, India, "
        "with low apartment blocks, trees and a small lane",
        "property": f"a home in {name}{', ' + city if city else ''}, India, shown as a paper house "
        "with a small garden",
        "blog": f"an editorial scene about {name}, Indian real estate, with paper buildings",
    }
    # HOUSE_STYLE travels as the generation instruction, so the prompt holds only the scene.
    return f"{scenes[subject_type]}."
