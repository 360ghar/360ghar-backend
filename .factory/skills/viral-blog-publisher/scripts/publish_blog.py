#!/usr/bin/env python3
"""Publish a blog post to Supabase via direct SQLAlchemy insert.

Usage:
    # From a JSON file
    python publish_blog.py --file blog_data.json

    # Inline via CLI args (minimal)
    python publish_blog.py --title "My Blog" --content "<p>Hello</p>"

    # Dry run (validate without writing)
    python publish_blog.py --file blog_data.json --dry-run

    # With image: provide cover_image_url and og_image_url in JSON,
    # or use --image-path to upload a local file to Supabase Storage

JSON file format:
{
    "title": "Blog Title",
    "content": "<p>HTML content</p>",
    "excerpt": "Short summary",
    "cover_image_url": "https://...",
    "meta_title": "SEO Title (max 60 chars)",
    "meta_description": "SERP snippet (max 160 chars)",
    "focus_keyword": "primary keyword",
    "canonical_url": "https://...",
    "og_image_url": "https://...",
    "categories": ["Real Estate", "Gurgaon"],
    "tags": ["keyword1", "keyword2"],
    "sources": [
        {"url": "https://...", "name": "Source Name", "type": "article", "retrieved_at": "2026-05-13"}
    ],
    "seo_metadata": {
        "schema_markup": {},
        "keyword_analysis": {},
        "trending_score": 80.0,
        "secondary_keywords": ["kw2", "kw3"]
    },
    "active": true,
    "publisher_user_id": 1
}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

# Add project root to path so app modules are importable
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.users import User
from app.models.enums import UserRole
from app.schemas.blog import BlogPostCreate, BlogSource, BlogSEOMetadata
from app.services.blog import create_blog_post
from sqlalchemy import select

logger = get_logger(__name__)


async def _upload_image_to_storage(file_path: str, blog_id: int) -> Optional[str]:
    """Upload a local image file to Supabase Storage blog-covers bucket."""
    path = Path(file_path)
    if not path.exists():
        print(f"[ERROR] Image file not found: {file_path}")
        return None

    from app.core.auth import get_supabase_storage_client
    storage = get_supabase_storage_client()
    bucket = "blog-covers"

    ext = path.suffix.lower()
    content_type = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/webp" if ext == ".webp" else "image/png"
    storage_path = f"blog-covers/{blog_id}{ext}"

    try:
        with open(path, "rb") as f:
            storage.storage.from_(bucket).upload(
                storage_path,
                f.read(),
                {"content-type": content_type, "upsert": "true"},
            )
        public_url = storage.storage.from_(bucket).get_public_url(storage_path)
        print(f"  Image uploaded: {public_url}")
        return public_url
    except Exception as e:
        print(f"[ERROR] Image upload failed: {e}")
        return None


async def _get_publisher_user(db, user_id: int | None) -> User | None:
    if user_id is None:
        # Try to find any admin user
        result = await db.execute(
            select(User).where(User.role == UserRole.admin.value).limit(1)
        )
        return result.scalar_one_or_none()
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user and user.role == UserRole.admin.value:
        return user
    return None


async def publish(data: dict, *, dry_run: bool = False, publisher_user_id: int | None = None, image_path: str | None = None) -> dict:
    async with AsyncSessionLocal() as db:
        async with db.begin():
            publisher = await _get_publisher_user(db, publisher_user_id or data.get("publisher_user_id"))
            if not publisher:
                raise SystemExit(
                    "No admin user found. Set publisher_user_id in JSON or pass --publisher-user-id."
                )

            # Build structured sources
            sources = []
            for s in data.get("sources", []):
                if isinstance(s, dict):
                    sources.append(BlogSource(**s))
                else:
                    sources.append(s)

            # Build SEO metadata
            seo_meta = data.get("seo_metadata")
            if seo_meta and isinstance(seo_meta, dict):
                seo_meta = BlogSEOMetadata(**seo_meta)

            # Handle local image upload
            cover_url = data.get("cover_image_url")
            og_url = data.get("og_image_url")
            if image_path and not dry_run:
                # We need a blog_id first — create with placeholder, then update
                # Actually we can compute a deterministic path using slug
                pass  # handled after creation below

            payload = BlogPostCreate(
                title=data["title"],
                content=data["content"],
                excerpt=data.get("excerpt"),
                cover_image_url=cover_url,
                categories=data.get("categories", []),
                tags=data.get("tags", []),
                active=data.get("active", False),
                meta_title=data.get("meta_title"),
                meta_description=data.get("meta_description"),
                focus_keyword=data.get("focus_keyword"),
                canonical_url=data.get("canonical_url"),
                og_image_url=og_url,
                published_at=data.get("published_at"),
                sources=sources or None,
                seo_metadata=seo_meta,
            )

            if dry_run:
                print("[DRY RUN] Blog payload validated successfully:")
                print(f"  Title: {payload.title}")
                print(f"  Slug: {payload.title.lower().replace(' ', '-')[:60]}")
                print(f"  Meta Title: {payload.meta_title}")
                print(f"  Meta Description: {payload.meta_description}")
                print(f"  Focus Keyword: {payload.focus_keyword}")
                print(f"  Categories: {payload.categories}")
                print(f"  Tags: {payload.tags}")
                print(f"  Sources: {len(sources)}")
                print(f"  Active: {payload.active}")
                print(f"  Cover Image: {cover_url or 'none'}")
                print(f"  OG Image: {og_url or 'none'}")
                if image_path:
                    print(f"  Image Path (would upload): {image_path}")
                print(f"  Publisher: {publisher.id} ({publisher.phone})")
                return {"dry_run": True, "title": payload.title}

            created = await create_blog_post(db, payload, publisher)

            # Upload local image if provided
            if image_path:
                uploaded_url = await _upload_image_to_storage(image_path, created.id)
                if uploaded_url:
                    from sqlalchemy import text
                    await db.execute(text("""
                        UPDATE blog_posts SET cover_image_url = :url, og_image_url = :url WHERE id = :pid
                    """), {"url": uploaded_url, "pid": created.id})

            print(f"Blog published successfully!")
            print(f"  ID: {created.id}")
            print(f"  Title: {created.title}")
            print(f"  Slug: {created.slug}")
            print(f"  Active: {created.active}")
            print(f"  Reading Time: {created.reading_time_minutes} min")
            print(f"  Word Count: {created.word_count}")
            print(f"  Meta Title: {created.meta_title}")
            print(f"  Cover Image: {created.cover_image_url or 'none'}")
            return {"id": created.id, "slug": created.slug, "title": created.title}


def main():
    parser = argparse.ArgumentParser(description="Publish a blog post to Supabase")
    parser.add_argument("--file", "-f", type=str, help="Path to JSON file with blog data")
    parser.add_argument("--title", "-t", type=str, help="Blog title (inline mode)")
    parser.add_argument("--content", "-c", type=str, help="Blog HTML content (inline mode)")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing")
    parser.add_argument("--publisher-user-id", type=int, help="Admin user ID to publish as")
    parser.add_argument("--image-path", type=str, help="Local image file to upload as cover image")
    args = parser.parse_args()

    if args.file:
        with open(args.file) as f:
            data = json.load(f)
    elif args.title and args.content:
        data = {"title": args.title, "content": args.content}
    else:
        parser.error("Provide --file or both --title and --content")

    result = asyncio.run(publish(data, dry_run=args.dry_run, publisher_user_id=args.publisher_user_id, image_path=args.image_path))
    if result.get("dry_run"):
        sys.exit(0)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
