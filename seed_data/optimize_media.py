#!/usr/bin/env python3
"""One-time optimizer for seed_data/media/ images.

Converts user PNG avatars to WebP with downscaling, and blog images
to WebP at the same dimensions. This reduces storage and bandwidth
with no perceptible quality loss for web/mobile display.

Usage:
    python seed_data/optimize_media.py                    # optimize in-place
    python seed_data/optimize_media.py --backup           # keep originals in _backup/
    python seed_data/optimize_media.py --dry-run          # report only, write nothing
    python seed_data/optimize_media.py --skip-blogs       # skip blog images
    python seed_data/optimize_media.py --users-only       # only user avatars
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Pillow is required: uv pip install Pillow", file=sys.stderr)
    sys.exit(1)

MEDIA_DIR = Path(__file__).parent / "media"
USERS_DIR = MEDIA_DIR / "users"
BLOGS_DIR = MEDIA_DIR / "blogs"
BACKUP_DIR = MEDIA_DIR / "_backup"

AVATAR_MAX_DIM = 512
AVATAR_QUALITY = 85
BLOG_QUALITY = 80

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}


@dataclass
class OptimizeResult:
    original_path: Path
    new_path: Path
    original_size: int
    new_size: int
    original_dims: tuple[int, int]
    new_dims: tuple[int, int]
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class BatchResult:
    results: list[OptimizeResult] = field(default_factory=list)
    total_original: int = 0
    total_new: int = 0
    skipped: int = 0
    errors: int = 0

    def add(self, r: OptimizeResult) -> None:
        self.results.append(r)
        if r.skipped:
            self.skipped += 1
        else:
            self.total_original += r.original_size
            self.total_new += r.new_size


def optimize_avatar(
    path: Path,
    max_dim: int = AVATAR_MAX_DIM,
    quality: int = AVATAR_QUALITY,
    dry_run: bool = False,
    backup: bool = False,
) -> OptimizeResult:
    """Convert a single user PNG to WebP with downscaling."""
    new_path = path.with_suffix(".webp")
    original_size = path.stat().st_size

    if dry_run:
        with Image.open(path) as img:
            orig_dims = img.size
            w, h = img.size
            if max(w, h) > max_dim:
                ar = w / h
                if w >= h:
                    new_w = max_dim
                    new_h = int(max_dim / ar)
                else:
                    new_h = max_dim
                    new_w = int(max_dim * ar)
            else:
                new_w, new_h = w, h
        return OptimizeResult(
            original_path=path,
            new_path=new_path,
            original_size=original_size,
            new_size=0,
            original_dims=orig_dims,
            new_dims=(new_w, new_h),
        )

    with Image.open(path) as img:
        original_dims = img.size
        rgb_img = img.convert("RGB") if img.mode in ("RGBA", "P", "LA") else img

        w, h = rgb_img.size
        if max(w, h) > max_dim:
            ar = w / h
            if w >= h:
                new_w = max_dim
                new_h = int(max_dim / ar)
            else:
                new_h = max_dim
                new_w = int(max_dim * ar)
            resized = rgb_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        else:
            new_w, new_h = w, h
            resized = rgb_img

        if backup:
            backup_path = BACKUP_DIR / "users" / path.name
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(backup_path))

        resized.save(str(new_path), format="WEBP", quality=quality, optimize=True, method=6)

        if rgb_img is not img:
            rgb_img.close()
        if resized is not rgb_img:
            resized.close()

    new_size = new_path.stat().st_size
    if not backup and path.exists() and path != new_path:
        path.unlink()

    return OptimizeResult(
        original_path=path,
        new_path=new_path,
        original_size=original_size,
        new_size=new_size,
        original_dims=original_dims,
        new_dims=(new_w, new_h),
    )


def optimize_blog_image(
    path: Path,
    quality: int = BLOG_QUALITY,
    dry_run: bool = False,
    backup: bool = False,
) -> OptimizeResult:
    """Convert a blog image to WebP (same dimensions)."""
    if path.suffix.lower() == ".webp":
        return OptimizeResult(
            original_path=path,
            new_path=path,
            original_size=path.stat().st_size,
            new_size=path.stat().st_size,
            original_dims=(0, 0),
            new_dims=(0, 0),
            skipped=True,
            skip_reason="already WebP",
        )

    new_path = path.with_suffix(".webp")
    original_size = path.stat().st_size

    if dry_run:
        with Image.open(path) as img:
            orig_dims = img.size
        return OptimizeResult(
            original_path=path,
            new_path=new_path,
            original_size=original_size,
            new_size=0,
            original_dims=orig_dims,
            new_dims=orig_dims,
        )

    with Image.open(path) as img:
        original_dims = img.size
        rgb_img = img.convert("RGB") if img.mode in ("RGBA", "P", "LA") else img

        if backup:
            backup_path = BACKUP_DIR / "blogs" / path.name
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(backup_path))

        rgb_img.save(str(new_path), format="WEBP", quality=quality, optimize=True, method=6)

        if rgb_img is not img:
            rgb_img.close()

    new_size = new_path.stat().st_size
    if not backup and path.exists() and path != new_path:
        path.unlink()

    return OptimizeResult(
        original_path=path,
        new_path=new_path,
        original_size=original_size,
        new_size=new_size,
        original_dims=original_dims,
        new_dims=original_dims,
    )


def process_directory(
    dir_path: Path,
    processor_name: str,
    processor: callable,
    dry_run: bool,
    backup: bool,
) -> BatchResult:
    """Process all image files in a directory."""
    result = BatchResult()
    files = sorted(
        f for f in dir_path.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS and not f.name.startswith(".")
    )

    if not files:
        print(f"\n  No image files found in {dir_path}")
        return result

    print(f"\n  Processing {len(files)} {processor_name} images from {dir_path}...")
    for f in files:
        try:
            r = processor(f, dry_run=dry_run, backup=backup)
            result.add(r)
            if r.skipped:
                print(f"    SKIP  {f.name} ({r.skip_reason})")
            elif dry_run:
                pct = ""
                print(f"    WOULD {f.name} → {r.new_path.name}  {r.original_dims} → {r.new_dims}")
            else:
                pct = f"({r.new_size / r.original_size * 100:.0f}% of original)" if r.original_size else ""
                print(f"    OK    {f.name} → {r.new_path.name}  {r.original_size / 1024:.0f}KB → {r.new_size / 1024:.0f}KB {pct}")
        except Exception as e:
            result.errors += 1
            print(f"    ERROR {f.name}: {e}")

    return result


def fmt_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / 1024:.0f} KB"


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimize seed_data/media/ images for web delivery")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change, write nothing")
    parser.add_argument("--backup", action="store_true", help="Move originals to _backup/ before converting")
    parser.add_argument("--skip-blogs", action="store_true", help="Skip blog image optimization")
    parser.add_argument("--users-only", action="store_true", help="Only process user avatars (same as --skip-blogs)")
    parser.add_argument("--avatar-max-dim", type=int, default=AVATAR_MAX_DIM, help=f"Max avatar dimension (default: {AVATAR_MAX_DIM})")
    parser.add_argument("--avatar-quality", type=int, default=AVATAR_QUALITY, help=f"Avatar WebP quality (default: {AVATAR_QUALITY})")
    parser.add_argument("--blog-quality", type=int, default=BLOG_QUALITY, help=f"Blog WebP quality (default: {BLOG_QUALITY})")
    args = parser.parse_args()

    skip_blogs = args.skip_blogs or args.users_only
    grand_original = 0
    grand_new = 0

    print("=" * 60)
    print("  seed_data/media Image Optimizer")
    print("=" * 60)
    if args.dry_run:
        print("  [DRY RUN] No files will be written")
    if args.backup:
        print(f"  [BACKUP] Originals moved to {BACKUP_DIR.relative_to(MEDIA_DIR.parent.parent)}")

    # Process user avatars
    if USERS_DIR.exists():
        print(f"\n--- User Avatars (WebP q={args.avatar_quality}, max {args.avatar_max_dim}px) ---")
        user_result = process_directory(
            USERS_DIR,
            "avatar",
            lambda p, dry_run=args.dry_run, backup=args.backup: optimize_avatar(
                p, max_dim=args.avatar_max_dim, quality=args.avatar_quality, dry_run=dry_run, backup=backup,
            ),
            dry_run=args.dry_run,
            backup=args.backup,
        )
        grand_original += user_result.total_original
        grand_new += user_result.total_new
        if user_result.results:
            print(f"\n  Avatars: {len(user_result.results)} files, {fmt_size(user_result.total_original)} → {fmt_size(user_result.total_new)}")
            if user_result.total_original:
                print(f"  Reduction: {(1 - user_result.total_new / user_result.total_original) * 100:.1f}%")
    else:
        print(f"\n  User directory not found: {USERS_DIR}")

    # Process blog images
    if not skip_blogs and BLOGS_DIR.exists():
        print(f"\n--- Blog Images (WebP q={args.blog_quality}, same dimensions) ---")
        blog_result = process_directory(
            BLOGS_DIR,
            "blog",
            lambda p, dry_run=args.dry_run, backup=args.backup: optimize_blog_image(
                p, quality=args.blog_quality, dry_run=dry_run, backup=backup,
            ),
            dry_run=args.dry_run,
            backup=args.backup,
        )
        grand_original += blog_result.total_original
        grand_new += blog_result.total_new
        if blog_result.results:
            print(f"\n  Blogs: {len(blog_result.results)} files, {fmt_size(blog_result.total_original)} → {fmt_size(blog_result.total_new)}")
            if blog_result.total_original:
                print(f"  Reduction: {(1 - blog_result.total_new / blog_result.total_original) * 100:.1f}%")
    elif not skip_blogs:
        print(f"\n  Blog directory not found: {BLOGS_DIR}")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  TOTAL: {fmt_size(grand_original)} → {fmt_size(grand_new)}")
    if grand_original:
        print(f"  Overall reduction: {(1 - grand_new / grand_original) * 100:.1f}%")
        print(f"  Saved: {fmt_size(grand_original - grand_new)}")
    print("=" * 60)

    if not args.dry_run:
        print("\n  Next steps:")
        print("  1. Verify optimized images look correct")
        print("  2. Regenerate seed JSON:  uv run python seed_data/generators/01_generate_seed_data.py")
        print("  3. Re-seed database:      uv run python seed_data/01_load_all.py")


if __name__ == "__main__":
    main()
