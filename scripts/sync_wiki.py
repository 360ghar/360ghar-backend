"""Sync a hierarchical `.wiki/` source tree into a flat GitHub wiki checkout.

GitHub wiki repositories are FLAT: they do not support subdirectories. This
script walks the hierarchical source tree (e.g. `.wiki/`) and writes a flat
copy into the destination (e.g. the cloned `wiki` repo checkout):

- `overview/index.md`     -> `overview--index.md`
- `features/mcp-servers.md` -> `features--mcp-servers.md`
- `video/overview.mp4`    -> `video--overview.mp4`

Special GitHub wiki filenames keep their bare names and live at the root:
`_Sidebar.md`, `_Footer.md`, `Home.md`.

Relative markdown links inside `.md` files are rewritten so they continue to
resolve in the flat layout (e.g. `](../foo/bar.md)` -> `](foo--bar.md)`).

Usage:
    python3 scripts/sync_wiki.py .wiki wiki
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

# Files GitHub wiki treats specially — they must sit at the repo root with
# their exact names, never flattened.
SPECIAL_FILES: frozenset[str] = frozenset({"_Sidebar.md", "_Footer.md", "Home.md"})

# Files/directories that are NOT wiki pages and must be skipped during sync.
# `node_modules` appears when the video has been rendered locally; `.wiki-meta.json`
# is build metadata for incremental regen, not a published page.
SKIP_NAMES: frozenset[str] = frozenset({"node_modules", ".wiki-meta.json"})

# Matches markdown reference-style links/images: `](<target>)` or `](<target> "title")`.
# Captures the inner target (path + optional anchor) so we can rewrite just the path.
_LINK_RE = re.compile(
    r"""(?P<prefix>!?\[)(?P<label>[^\]]*?)\]\((?P<target>[^)\s]+)(?P<after>\s+"[^"]*")?\)""",
)

# File extensions that should be treated as text (markdown link rewriting applies).
_TEXT_EXTENSIONS: frozenset[str] = frozenset({".md"})


def flatten_relative_path(link_target: str, current_source_file: Path, source_root: Path) -> str:
    """Rewrite a relative link target to its flattened wiki name.

    Resolves the link relative to the file it appears in, then flattens the
    resolved path (relative to the source root) into a single filename using
    `--` as the directory separator. Anchors (`#section`) and query strings
    are preserved. Absolute URLs (`http://`, `https://`, `mailto:`) and
    non-path targets are returned unchanged.

    Args:
        link_target: The raw href from a markdown link, e.g. `../foo/bar.md#sec`.
        current_source_file: The source `.md` file containing the link.
        source_root: The root of the source wiki tree (e.g. `.wiki`).

    Returns:
        The rewritten target string, e.g. `foo--bar.md#sec`.
    """
    # Leave absolute URLs and non-path targets untouched.
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", link_target) or link_target.startswith(
        ("mailto:", "tel:")
    ):
        return link_target

    # Split off any anchor / query so we only rewrite the path portion.
    anchor = ""
    path_part = link_target
    for sep in ("#", "?"):
        if sep in path_part:
            idx = path_part.index(sep)
            anchor = path_part[idx:] + anchor
            path_part = path_part[:idx]

    if not path_part:
        # Pure anchor link (e.g. `#section`) — keep as-is.
        return link_target

    # Resolve the link relative to the file it appears in.
    current_dir = current_source_file.parent
    resolved = (current_dir / path_part).resolve()

    # Compute the path relative to the source root.
    try:
        rel = resolved.relative_to(source_root.resolve())
    except ValueError:
        # Resolved path escapes the source root — leave it unchanged.
        return link_target

    parts = rel.parts
    if not parts:
        return link_target

    # Special files keep their bare names even when referenced from a subdir.
    name = parts[-1]
    if name in SPECIAL_FILES:
        flattened = name
    else:
        flattened = "--".join(parts)

    return f"{flattened}{anchor}"


def rewrite_links(content: str, current_source_file: Path, source_root: Path) -> str:
    """Rewrite all markdown links/images in `content` to flattened targets."""
    # Normalize Windows line endings to Unix so regex matching is consistent.
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")

    def _replace(match: re.Match[str]) -> str:
        target = match.group("target")
        rewritten = flatten_relative_path(target, current_source_file, source_root)
        after = match.group("after") or ""
        return f"{match.group('prefix')}{match.group('label')}]({rewritten}{after})"

    return _LINK_RE.sub(_replace, normalized)


def dest_filename(source_file: Path, source_root: Path) -> str:
    """Compute the flattened destination filename for a source file."""
    rel = source_file.relative_to(source_root)
    parts = rel.parts
    name = parts[-1]
    if name in SPECIAL_FILES:
        return name
    return "--".join(parts)


def clear_dest(dest_root: Path) -> None:
    """Remove all contents of `dest_root` except the `.git` directory."""
    if not dest_root.exists():
        dest_root.mkdir(parents=True, exist_ok=True)
        return
    for child in dest_root.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def sync_file(source_file: Path, source_root: Path, dest_root: Path) -> Path:
    """Copy (and optionally rewrite) a single source file into `dest_root`."""
    dest_name = dest_filename(source_file, source_root)
    dest_path = dest_root / dest_name

    if source_file.suffix in _TEXT_EXTENSIONS:
        text = source_file.read_text(encoding="utf-8")
        rewritten = rewrite_links(text, source_file, source_root)
        dest_path.write_text(rewritten, encoding="utf-8")
    else:
        # Binary copy for mp4, png, etc.
        shutil.copyfile(source_file, dest_path)

    return dest_path


def iter_source_files(source_root: Path) -> list[Path]:
    """Yield all regular files under `source_root`, sorted for determinism.

    Skips `node_modules` and `.wiki-meta.json` (not wiki pages).
    """
    if not source_root.exists():
        return []
    results: list[Path] = []
    for p in source_root.rglob("*"):
        if not p.is_file():
            continue
        # Skip excluded names anywhere in the path.
        if any(part in SKIP_NAMES for part in p.relative_to(source_root).parts):
            continue
        results.append(p)
    return sorted(results)


def sync(source_root: Path, dest_root: Path) -> list[Path]:
    """Sync the entire source tree into the flat dest layout.

    Args:
        source_root: Directory containing the hierarchical wiki (e.g. `.wiki`).
        dest_root: Directory of the cloned wiki repo checkout (e.g. `wiki`).

    Returns:
        List of destination paths that were written.
    """
    if not source_root.exists():
        raise FileNotFoundError(f"Source wiki directory not found: {source_root}")

    clear_dest(dest_root)

    written: list[Path] = []
    for source_file in iter_source_files(source_root):
        dest_path = sync_file(source_file, source_root, dest_root)
        written.append(dest_path)

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync a hierarchical .wiki/ tree into a flat GitHub wiki checkout.",
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Source directory (hierarchical wiki, e.g. .wiki)",
    )
    parser.add_argument(
        "dest",
        type=Path,
        help="Destination directory (flat wiki repo checkout, e.g. wiki)",
    )
    args = parser.parse_args(argv)

    source_root: Path = args.source.resolve()
    dest_root: Path = args.dest.resolve()

    try:
        written = sync(source_root, dest_root)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Synced {len(written)} file(s) from {source_root} -> {dest_root}:")
    for path in written:
        print(f"  + {path.relative_to(dest_root)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
