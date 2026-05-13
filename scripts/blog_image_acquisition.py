#!/usr/bin/env python3
"""
Blog Cover Image Acquisition Script.

Recovers, downloads, and acquires cover images for blog posts:
- Phase 1: Recover existing hotlinked images (download + re-upload to Supabase Storage)
- Phase 2: Acquire images from Pixabay/Pexels for posts without images
- Phase 3: Update DB with Supabase Storage public URLs

Usage:
  # Dry run (no changes)
  uv run python scripts/blog_image_acquisition.py --dry-run

  # Recover existing hotlinked images only
  uv run python scripts/blog_image_acquisition.py --phase recover

  # Acquire images for posts without images (Pixabay + Pexels)
  uv run python scripts/blog_image_acquisition.py --phase acquire --limit 50

  # Run both phases
  uv run python scripts/blog_image_acquisition.py --phase all

  # Resume (skip posts that already have Supabase Storage URLs)
  uv run python scripts/blog_image_acquisition.py --phase acquire --resume
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
from datetime import datetime, UTC

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

MEDIA_DIR = PROJECT_ROOT / "seed_data" / "media" / "blogs"

# Rate limits: Pixabay ~5000/hr, Pexels ~200/hr
PIXABAY_DELAY = 0.5  # seconds between requests
PEXELS_DELAY = 18    # seconds between requests (200/hr = ~18s, stay within rate limit)
UPLOAD_DELAY = 0.5   # seconds between Supabase uploads
DOWNLOAD_TIMEOUT = 30 # seconds for image download

# Minimum image dimensions for blog cover
MIN_WIDTH = 800
MIN_HEIGHT = 400
OG_WIDTH = 1200
OG_HEIGHT = 630


def _slugify_search(title: str, focus_keyword: str | None = None, categories: list[str] | None = None) -> str:
    """Derive a search query from blog title, focus_keyword, and categories.

    Strategy: Extract the TOPIC (not specific names/numbers) and add real estate context.
    Uses priority-ordered matching: specific topics (celebrity, villa, vastu) checked before
    generic ones (apartment, real estate) to avoid generic duplicates.
    """
    title_lower = title.lower()

    # Priority-ordered topic patterns: most specific first, generic last
    # Each tuple: (search_term, list_of_keywords that trigger it)
    TOPIC_RULES = [
        # Spiritual / cultural (very specific)
        ("vastu home interior", ["vastu"]),
        ("feng shui home decor", ["feng shui"]),
        ("home temple design", ["temple", "pooja"]),
        ("meditation home peace", ["singing bowl", "meditation", "shivratr"]),
        ("spiritual home", ["navratr", "maha shivratri"]),
        ("festive home decoration", ["diwali", "holi", "navratr"]),
        ("romantic home decor", ["valentine"]),
        ("indoor plants home", ["indoor plant", "air purifying plant"]),
        ("home garden green", ["garden", "terrace garden"]),
        ("home water feature", ["water fountain"]),

        # Celebrity / specific person (before generic "luxury" or "garden")
        ("luxury celebrity home", ["celebrity", "bollywood", "cricketer", "net worth", "residence", "duplex", "crore sale"]),
        ("mumbai luxury apartment", ["bandra", "juhu", "pali hill", "worli", "poes garden"]),
        ("mumbai residential building", ["malad", "andheri"]),
        ("affordable housing mumbai", ["mhad", "lottery"]),

        # Property types (before generic "apartment")
        ("luxury villa exterior", ["villa"]),
        ("paying guest accommodation", ["pg "]),
        ("shared apartment living", ["flatmate"]),
        ("residential plot land", ["plot"]),

        # Specific features (before generic)
        ("smart home technology", ["smart home"]),
        ("virtual reality property", ["virtual tour", "360 tour"]),
        ("green building sustainable", ["sustainability", "green building"]),
        ("home interior design", ["home decor", "interior design"]),

        # Infrastructure / policy (specific)
        ("metro city real estate", ["metro"]),
        ("highway real estate development", ["expressway", "highway"]),
        ("infrastructure development", ["flyover", "bridge"]),
        ("airport development area", ["airport"]),
        ("stadium area development", ["stadium"]),
        ("real estate regulation", ["rera"]),
        ("real estate investment", ["gst ", "investment"]),
        ("property valuation", ["circle rate"]),
        ("property registration", ["stamp duty"]),
        ("property documents", ["documentation"]),
        ("property legal", ["legal checklist", "legal "]),
        ("home loan property", ["home loan"]),
        ("home finance", ["emi "]),
        ("property tax", ["tax "]),
        ("city pollution buildings", ["pollution"]),
        ("real estate verification", ["verified listing", "verified property"]),

        # Location-based (before generic)
        ("luxury residential golf course", ["golf course"]),
        ("expressway development", ["dwarka "]),
        ("gurgaon city buildings", ["gurgaon", "gurugram"]),
        ("ahmedabad residential building", ["ahmedabad"]),
        ("delhi residential buildings", ["delhi"]),
        ("bangalore apartment complex", ["bangalore"]),
        ("pune apartment building", ["pune"]),
        ("hyderabad residential complex", ["hyderabad"]),
        ("kolkata residential building", ["kolkata"]),

        # Property size (before generic "apartment")
        ("apartment building", ["2bhk", "2 bhk"]),
        ("modern apartment interior", ["3bhk", "3 bhk"]),
        ("luxury apartment interior", ["4bhk", "4 bhk", "5bhk"]),

        # Generic property types (lowest priority)
        ("luxury apartment building", ["luxury"]),
        ("premium apartment interior", ["premium"]),
        ("affordable housing", ["affordable"]),
        ("rental apartment", ["rental", " rent "]),
        ("apartment interior", ["flat ", "apartment"]),
        ("residential area buildings", ["sector", "locality"]),

        # Seasonal / environment
        ("rainy season home", ["monsoon"]),
        ("home booking registration", ["booking"]),
        ("affordable housing scheme", ["scheme"]),
    ]

    for search_term, keywords in TOPIC_RULES:
        for kw in keywords:
            if kw in title_lower:
                return search_term

    # Fallback: extract generic real estate terms from title
    text = title
    if focus_keyword:
        text += " " + focus_keyword
    words = re.findall(r"[a-zA-Z0-9]+'?[a-zA-Z0-9]*", text)
    stop = {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "it", "its", "are", "was", "were",
        "be", "been", "being", "have", "has", "had", "do", "does", "did",
        "will", "would", "could", "should", "may", "might", "can", "need",
        "this", "that", "these", "those", "what", "which", "who", "whom",
        "how", "why", "when", "where", "all", "each", "every", "both", "few",
        "more", "most", "other", "some", "such", "no", "not", "only", "same",
        "so", "than", "too", "very", "just", "about", "up", "out", "if",
        "their", "your", "our", "my", "his", "her", "inside", "look",
        "case", "study", "guide", "tips", "complete", "ultimate",
        "comprehensive", "detailed", "deep", "dive", "exploring",
        "path", "right", "new", "best", "top", "vs", "1", "2", "3", "4",
    }
    clean = [w for w in words if w.lower() not in stop and len(w) > 2 and not w.isdigit()]
    query = " ".join(clean[:3]).lower()

    if not query:
        query = "real estate"

    if not any(kw in query for kw in ["home", "house", "apartment", "flat", "villa", "property", "real estate", "building", "interior", "architecture"]):
        query += " real estate"

    return query[:200]


class ImageAcquisition:
    def __init__(self, dry_run: bool = False, resume: bool = False):
        self.dry_run = dry_run
        self.resume = resume
        self.pixabay_key = os.environ.get("PIXABAY_API_KEY", "")
        self.pexels_key = os.environ.get("PEXELS_API_KEY", "")
        self._used_image_urls: set[str] = set()  # dedup: track used source URLs
        self.stats = {
            "recovered": 0,
            "recovered_failed": 0,
            "acquired_pixabay": 0,
            "acquired_pexels": 0,
            "acquired_failed": 0,
            "uploaded": 0,
            "upload_failed": 0,
            "skipped": 0,
            "db_updated": 0,
        }
        self._supabase_storage = None

    def _get_supabase_storage(self):
        """Lazy-init Supabase storage client."""
        if self._supabase_storage is None:
            from app.core.auth import get_supabase_storage_client
            self._supabase_storage = get_supabase_storage_client()
        return self._supabase_storage

    def _is_supabase_url(self, url: str) -> bool:
        """Check if URL is already a Supabase Storage public URL."""
        return "supabase.co" in url and "/storage/" in url

    async def _upload_to_supabase(self, file_path: Path, blog_id: int, ext: str) -> Optional[str]:
        """Upload image to Supabase Storage blog-covers bucket and return public URL."""
        if self.dry_run:
            return f"dry-run://blog-covers/{blog_id}{ext}"

        try:
            storage = self._get_supabase_storage()
            bucket = "blog-covers"
            storage_path = f"blog-covers/{blog_id}{ext}"

            with open(file_path, "rb") as f:
                content_type = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/webp" if ext == ".webp" else "image/png"
                # Delete existing file first (upsert not always reliable)
                try:
                    storage.storage.from_(bucket).remove([storage_path])
                except Exception:
                    pass
                storage.storage.from_(bucket).upload(
                    storage_path,
                    f.read(),
                    {"content-type": content_type},
                )

            public_url = storage.storage.from_(bucket).get_public_url(storage_path)
            self.stats["uploaded"] += 1
            return public_url
        except Exception as e:
            print(f"    [ERROR] Upload failed for blog {blog_id}: {e}")
            self.stats["upload_failed"] += 1
            return None

    async def _update_db(self, session: AsyncSession, blog_id: int, cover_url: str, og_url: str):
        """Update blog_posts cover_image_url and og_image_url."""
        if self.dry_run:
            self.stats["db_updated"] += 1
            return

        try:
            await session.execute(text("""
                UPDATE blog_posts
                SET cover_image_url = :cover, og_image_url = :og
                WHERE id = :pid
            """), {"cover": cover_url, "og": og_url, "pid": blog_id})
            self.stats["db_updated"] += 1
        except Exception as e:
            print(f"    [ERROR] DB update failed for blog {blog_id}: {e}")

    async def _download_image(self, client: httpx.AsyncClient, url: str, dest: Path) -> bool:
        """Download image from URL to local path. Validates it's a real image using Pillow."""
        try:
            resp = await client.get(url, timeout=DOWNLOAD_TIMEOUT, follow_redirects=True)
            if resp.status_code != 200 or len(resp.content) < 1000:
                return False
            # Verify it's a valid image (not HTML error pages, etc.)
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(resp.content))
                img.verify()
            except Exception:
                print(f"    [WARN] Downloaded content is not a valid image, skipping")
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return True
        except Exception as e:
            print(f"    [ERROR] Download failed: {e}")
        return False

    # ─── Phase 1: Recover existing hotlinked images ────────────────────────

    async def recover_existing(self, session: AsyncSession):
        """Download existing cover_image_urls and re-upload to Supabase Storage."""
        print("\n=== Phase 1: Recover Existing Hotlinked Images ===")

        r = await session.execute(text("""
            SELECT id, title, cover_image_url
            FROM blog_posts
            WHERE cover_image_url IS NOT NULL AND cover_image_url != ''
        """))
        posts = r.fetchall()
        print(f"Found {len(posts)} posts with existing cover_image_url")

        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            for idx, (pid, title, url) in enumerate(posts):
                if self.resume and self._is_supabase_url(url):
                    self.stats["skipped"] += 1
                    continue

                print(f"  [{idx+1}/{len(posts)}] Blog {pid}: {title[:60]}...")

                # Determine file extension from URL
                ext = self._ext_from_url(url)
                local_path = MEDIA_DIR / f"{pid}{ext}"

                # Download
                if await self._download_image(client, url, local_path):
                    # Upload to Supabase Storage
                    public_url = await self._upload_to_supabase(local_path, pid, ext)
                    if public_url:
                        await self._update_db(session, pid, public_url, public_url)
                        if not self.dry_run:
                            await session.commit()
                        self.stats["recovered"] += 1
                        print(f"    -> Recovered: {public_url[:80]}")
                    else:
                        self.stats["recovered_failed"] += 1
                else:
                    self.stats["recovered_failed"] += 1
                    print(f"    -> FAILED to download")

                await asyncio.sleep(UPLOAD_DELAY)

    # ─── Phase 2: Acquire images from Pixabay/Pexels ───────────────────────

    async def _search_pixabay(self, client: httpx.AsyncClient, query: str) -> Optional[str]:
        """Search Pixabay and return the best unused image URL."""
        if not self.pixabay_key:
            return None

        try:
            resp = await client.get(
                "https://pixabay.com/api/",
                params={
                    "key": self.pixabay_key,
                    "q": query,
                    "image_type": "photo",
                    "orientation": "horizontal",
                    "min_width": MIN_WIDTH,
                    "min_height": MIN_HEIGHT,
                    "per_page": 20,
                    "safesearch": "true",
                    "order": "popular",
                    "lang": "en",
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            hits = data.get("hits", [])
            for hit in hits:
                url = hit.get("largeImageURL") or hit.get("webformatURL")
                if url and url not in self._used_image_urls:
                    return url

            return None
        except Exception:
            return None

    async def _search_pexels(self, client: httpx.AsyncClient, query: str) -> Optional[str]:
        """Search Pexels and return the best unused image URL (landscape for OG tags)."""
        if not self.pexels_key:
            return None

        try:
            resp = await client.get(
                "https://api.pexels.com/v1/search",
                params={
                    "query": query,
                    "per_page": 15,
                    "orientation": "landscape",
                    "page": 1,
                },
                headers={"Authorization": self.pexels_key},
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            photos = data.get("photos", [])
            for photo in photos:
                src = photo.get("src", {})
                url = src.get("landscape") or src.get("large2x") or src.get("large")
                if url and url not in self._used_image_urls:
                    return url

            return None
        except Exception:
            return None

    async def acquire_images(self, session: AsyncSession, limit: int = 0):
        """Acquire cover images for posts without them via Pixabay/Pexels."""
        print("\n=== Phase 2: Acquire Images from Pixabay/Pexels ===")

        has_pixabay = bool(self.pixabay_key)
        has_pexels = bool(self.pexels_key)

        if not has_pixabay and not has_pexels:
            print("[ERROR] No API keys found. Set PIXABAY_API_KEY and/or PEXELS_API_KEY env vars.")
            return

        if has_pixabay:
            print(f"  Pixabay API: available")
        if has_pexels:
            print(f"  Pexels API: available")

        # Get posts without images
        r = await session.execute(text("""
            SELECT id, title, focus_keyword
            FROM blog_posts
            WHERE active = true
              AND (cover_image_url IS NULL OR cover_image_url = '')
            ORDER BY id
        """))
        posts = r.fetchall()

        if limit > 0:
            posts = posts[:limit]

        print(f"Found {len(posts)} active posts without cover images")

        # Get categories for each post
        post_categories = {}
        r = await session.execute(text("""
            SELECT bp.id, bc.name
            FROM blog_posts bp
            JOIN blog_post_categories bpc ON bp.id = bpc.post_id
            JOIN blog_categories bc ON bpc.category_id = bc.id
            WHERE bp.active = true AND (bp.cover_image_url IS NULL OR bp.cover_image_url = '')
        """))
        for pid, cat_name in r.fetchall():
            post_categories.setdefault(pid, []).append(cat_name)

        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            for idx, (pid, title, fk) in enumerate(posts):
                print(f"  [{idx+1}/{len(posts)}] Blog {pid}: {title[:60]}...")

                cats = post_categories.get(pid, [])
                search_query = _slugify_search(title, fk, cats)
                print(f"    Search: \"{search_query}\"")

                image_url = None
                source = None

                # Try Pixabay first (fast, high rate limit)
                if has_pixabay:
                    image_url = await self._search_pixabay(client, search_query)
                    if image_url:
                        source = "pixabay"
                    await asyncio.sleep(PIXABAY_DELAY)

                # Fallback to Pexels (quality, lower rate limit)
                if not image_url and has_pexels:
                    # Try broader query for Pexels
                    pexels_query = _slugify_search(title, fk, cats)
                    image_url = await self._search_pexels(client, pexels_query)
                    if image_url:
                        source = "pexels"
                    await asyncio.sleep(PEXELS_DELAY)

                # Second attempt: broader search
                if not image_url:
                    broad_query = " ".join(search_query.split()[:3])
                    if has_pexels and not source:
                        image_url = await self._search_pexels(client, broad_query)
                        if image_url:
                            source = "pexels"
                        await asyncio.sleep(PEXELS_DELAY)
                    if not image_url and has_pixabay:
                        image_url = await self._search_pixabay(client, broad_query)
                        if image_url:
                            source = "pixabay"
                        await asyncio.sleep(PIXABAY_DELAY)

                if not image_url:
                    self.stats["acquired_failed"] += 1
                    print(f"    -> NO IMAGE FOUND")
                    continue

                # Track image URL to prevent duplicates
                self._used_image_urls.add(image_url)

                # Download image
                ext = self._ext_from_url(image_url) or ".jpg"
                local_path = MEDIA_DIR / f"{pid}{ext}"

                if await self._download_image(client, image_url, local_path):
                    # Upload to Supabase Storage
                    public_url = await self._upload_to_supabase(local_path, pid, ext)
                    if public_url:
                        await self._update_db(session, pid, public_url, public_url)
                        if not self.dry_run:
                            await session.commit()
                        if source == "pixabay":
                            self.stats["acquired_pixabay"] += 1
                        else:
                            self.stats["acquired_pexels"] += 1
                        print(f"    -> Acquired ({source}): {public_url[:80]}")
                    else:
                        self.stats["acquired_failed"] += 1
                else:
                    self.stats["acquired_failed"] += 1
                    print(f"    -> Download failed for {source} image")

                await asyncio.sleep(UPLOAD_DELAY)

        # No final commit needed — commits happen per post above

    @staticmethod
    def _ext_from_url(url: str) -> str:
        """Extract file extension from URL."""
        # Remove query params
        path = url.split("?")[0].split("#")[0]
        for ext in (".webp", ".jpg", ".jpeg", ".png", ".gif"):
            if path.lower().endswith(ext):
                return ext
        # Default to .jpg for unknown
        return ".jpg"

    def print_summary(self):
        """Print final summary."""
        print("\n" + "=" * 60)
        print("ACQUISITION SUMMARY")
        print("=" * 60)
        if self.dry_run:
            print("  [DRY RUN — no changes made]")
        print(f"  Recovered existing:     {self.stats['recovered']}")
        print(f"  Recovery failed:        {self.stats['recovered_failed']}")
        print(f"  Acquired (Pixabay):     {self.stats['acquired_pixabay']}")
        print(f"  Acquired (Pexels):      {self.stats['acquired_pexels']}")
        print(f"  Acquisition failed:     {self.stats['acquired_failed']}")
        print(f"  Uploaded to Supabase:   {self.stats['uploaded']}")
        print(f"  Upload failed:          {self.stats['upload_failed']}")
        print(f"  Skipped (resume):       {self.stats['skipped']}")
        print(f"  DB rows updated:        {self.stats['db_updated']}")
        total = self.stats["recovered"] + self.stats["acquired_pixabay"] + self.stats["acquired_pexels"]
        print(f"  TOTAL IMAGES PROCURED:  {total}")


async def main():
    parser = argparse.ArgumentParser(description="Blog Cover Image Acquisition")
    parser.add_argument("--phase", choices=["recover", "acquire", "all"], default="all",
                        help="Which phase to run (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="No changes to DB or storage")
    parser.add_argument("--resume", action="store_true", help="Skip posts already having Supabase URLs")
    parser.add_argument("--limit", type=int, default=0, help="Max posts to process in acquire phase (0=all)")
    args = parser.parse_args()

    acq = ImageAcquisition(dry_run=args.dry_run, resume=args.resume)

    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        if args.phase in ("recover", "all"):
            await acq.recover_existing(session)

        if args.phase in ("acquire", "all"):
            await acq.acquire_images(session, limit=args.limit)

    acq.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
