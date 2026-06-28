from __future__ import annotations

"""Migration: add blog_post status/scheduled_at/preview_token columns.

Run:  uv run python scripts/migrate_blog_status.py
"""

import asyncio
import sys
from textwrap import dedent

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings


async def main() -> None:
    dsn = settings.ASYNC_DATABASE_URL
    engine = create_async_engine(dsn, pool_pre_ping=True)

    async def exec_sql(sql: str, *, commit: bool = True) -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SET LOCAL lock_timeout = '5000'"))
            await conn.execute(text(dedent(sql)))
            if commit:
                await conn.commit()

    # Step 1: add status column + backfill
    print("Adding status column ...")
    await exec_sql("""
        ALTER TABLE public.blog_posts
          ADD COLUMN IF NOT EXISTS status varchar DEFAULT 'draft'
    """)
    print("  Done")

    print("Backfilling status from active ...")
    async with engine.connect() as conn:
        await conn.execute(
            text("UPDATE public.blog_posts SET status = 'published' WHERE active = true AND status IS NULL")
        )
        await conn.execute(
            text("UPDATE public.blog_posts SET status = 'draft' WHERE (active = false OR active IS NULL) AND status IS NULL")
        )
        await conn.commit()
    print("  Done")

    # Step 2: add scheduled_at
    print("Adding scheduled_at column ...")
    await exec_sql("""
        ALTER TABLE public.blog_posts
          ADD COLUMN IF NOT EXISTS scheduled_at timestamp with time zone
    """)
    print("  Done")

    # Step 3: add preview_token
    print("Adding preview_token column ...")
    await exec_sql("""
        ALTER TABLE public.blog_posts
          ADD COLUMN IF NOT EXISTS preview_token varchar
    """)
    print("  Done")

    # Step 4: drop constraint if exists
    print("Dropping old constraint ...")
    try:
        await exec_sql("ALTER TABLE public.blog_posts DROP CONSTRAINT IF EXISTS blog_posts_preview_token_key")
        print("  Done")
    except Exception as e:
        print(f"  Skipped: {e}")

    # Step 5: indexes
    for idx_name, idx_sql in [
        ("idx_blog_posts_status", "CREATE INDEX IF NOT EXISTS idx_blog_posts_status ON public.blog_posts (status)"),
        (
            "idx_blog_posts_preview_token",
            "CREATE INDEX IF NOT EXISTS idx_blog_posts_preview_token ON public.blog_posts (preview_token) WHERE preview_token IS NOT NULL",
        ),
    ]:
        print(f"Creating index {idx_name} ...")
        try:
            await exec_sql(idx_sql)
            print(f"  Done")
        except Exception as e:
            print(f"  Skipped: {e}")

    await engine.dispose()
    print("Migration complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)
