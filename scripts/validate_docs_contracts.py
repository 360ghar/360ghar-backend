"""Validate the repository docs contract."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
DOC_DRIFT_CHECKLIST = (
    "Documentation drift checklist:\n"
    "- New public endpoint\n"
    "- New service domain\n"
    "- New MCP tool or widget\n"
    "- New background or scheduler flow\n"
    "- If any item changed, update the relevant doc in docs/ and docs/repo-contract.json"
)


@dataclass
class RepoContract:
    required_docs: list[str]
    top_level_paths: list[str]
    architecture_layers: list[str]
    required_doc_path_mentions: dict[str, list[str]]
    documented_endpoint_modules: list[str]
    documented_service_modules: list[str]
    documented_mcp_modules: list[str]

    @classmethod
    def load(cls, root: Path) -> RepoContract:
        contract_path = root / "docs" / "repo-contract.json"
        data = json.loads(contract_path.read_text())
        return cls(**data)


def _normalize_relative_path(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def _collect_python_modules(base: Path) -> list[str]:
    modules = [
        _normalize_relative_path(path, base)
        for path in base.rglob("*.py")
        if path.name != "__init__.py" and "__pycache__" not in path.parts
    ]
    return sorted(modules)


def _collect_endpoint_modules(root: Path) -> list[str]:
    endpoint_dir = root / "app" / "api" / "api_v1" / "endpoints"
    modules: list[str] = []
    # Top-level .py files (e.g., flatmates.py, agents.py)
    for path in endpoint_dir.glob("*.py"):
        if path.name != "__init__.py":
            modules.append(path.stem)
    # Sub-package modules (e.g., oauth/authorization.py -> oauth/authorization)
    for pkg_dir in endpoint_dir.iterdir():
        if pkg_dir.is_dir() and pkg_dir.name != "__pycache__":
            for py_file in pkg_dir.glob("*.py"):
                if py_file.name != "__init__.py":
                    modules.append(f"{pkg_dir.name}/{py_file.stem}")
    return sorted(modules)


def _extract_markdown_links(text: str) -> list[str]:
    return [target.strip() for _, target in MARKDOWN_LINK_RE.findall(text)]


def _resolve_local_link(base_dir: Path, target: str) -> Path | None:
    if not target or target.startswith("#"):
        return None
    if "://" in target or target.startswith("mailto:"):
        return None

    path_part = target.split("#", 1)[0]
    if not path_part:
        return None

    return (base_dir / path_part).resolve()


def _validate_markdown_links(root: Path, relative_paths: Iterable[str]) -> list[str]:
    errors: list[str] = []
    for relative_path in relative_paths:
        file_path = root / relative_path
        text = file_path.read_text()
        for target in _extract_markdown_links(text):
            resolved = _resolve_local_link(file_path.parent, target)
            if resolved is None:
                continue
            if not resolved.exists():
                errors.append(
                    f"{relative_path} has a broken local link: {target}"
                )
    return errors


def _compare_inventory(
    label: str,
    current: list[str],
    documented: list[str],
) -> list[str]:
    errors: list[str] = []
    current_set = set(current)
    documented_set = set(documented)

    missing = sorted(current_set - documented_set)
    stale = sorted(documented_set - current_set)

    if missing:
        errors.append(f"Undocumented {label}: {', '.join(missing)}")
    if stale:
        errors.append(f"Stale {label} entries: {', '.join(stale)}")

    return errors


def validate_repo(root: Path) -> list[str]:
    contract = RepoContract.load(root)
    errors: list[str] = []

    required_docs = ["AGENTS.md", *contract.required_docs]

    for relative_path in required_docs:
        if not (root / relative_path).exists():
            errors.append(f"Missing required doc: {relative_path}")

    for relative_path in contract.top_level_paths:
        if not (root / relative_path).exists():
            errors.append(f"Missing required top-level path: {relative_path}")

    for relative_path in contract.architecture_layers:
        if not (root / relative_path).exists():
            errors.append(f"Missing declared architecture layer: {relative_path}")

    errors.extend(_validate_markdown_links(root, required_docs))

    for relative_path, mentions in contract.required_doc_path_mentions.items():
        file_path = root / relative_path
        if not file_path.exists():
            errors.append(f"Missing doc for path-mention check: {relative_path}")
            continue
        text = file_path.read_text()
        for mention in mentions:
            if mention not in text:
                errors.append(f"{relative_path} must mention `{mention}`")

    current_endpoints = _collect_endpoint_modules(root)
    errors.extend(
        _compare_inventory(
            "endpoint modules",
            current_endpoints,
            sorted(contract.documented_endpoint_modules),
        )
    )

    current_services = _collect_python_modules(root / "app" / "services")
    errors.extend(
        _compare_inventory(
            "service modules",
            current_services,
            sorted(contract.documented_service_modules),
        )
    )

    current_mcp_modules = _collect_python_modules(root / "app" / "mcp")
    errors.extend(
        _compare_inventory(
            "MCP modules",
            current_mcp_modules,
            sorted(contract.documented_mcp_modules),
        )
    )

    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = validate_repo(root)
    if errors:
        print("Docs contract validation failed:")
        for error in errors:
            print(f"- {error}")
        print()
        print(DOC_DRIFT_CHECKLIST)
        return 1

    print("Docs contract validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
