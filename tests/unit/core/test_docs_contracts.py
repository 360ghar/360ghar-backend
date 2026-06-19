from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_docs_contracts import validate_repo

ROOT = Path(__file__).resolve().parents[3]


def _write_markdown(path: Path, title: str) -> None:
    path.write_text(f"# {title}\n")


def test_docs_contract_validation_passes_for_current_repo():
    assert validate_repo(ROOT) == []


def test_docs_contract_validation_reports_undocumented_endpoint_module(tmp_path: Path):
    (tmp_path / "app" / "api" / "api_v1" / "endpoints").mkdir(parents=True)
    (tmp_path / "app" / "services").mkdir(parents=True)
    (tmp_path / "app" / "mcp").mkdir(parents=True)
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)

    _write_markdown(tmp_path / "AGENTS.md", "Agents")
    _write_markdown(tmp_path / "docs" / "architecture-contract.md", "Architecture")
    _write_markdown(tmp_path / "docs" / "contribution-contract.md", "Contribution")
    _write_markdown(tmp_path / "docs" / "testing-contract.md", "Testing")
    _write_markdown(tmp_path / "docs" / "terminology-and-ownership.md", "Terminology")

    (tmp_path / "app" / "api" / "api_v1" / "endpoints" / "sample.py").write_text("router = None\n")

    contract = {
        "required_docs": [
            "docs/architecture-contract.md",
            "docs/contribution-contract.md",
            "docs/testing-contract.md",
            "docs/terminology-and-ownership.md",
            "docs/repo-contract.json",
        ],
        "top_level_paths": [
            "AGENTS.md",
            "app",
            "app/api",
            "app/mcp",
            "app/services",
            "docs",
            "scripts",
            ".github/workflows",
        ],
        "architecture_layers": [
            "app/api",
            "app/mcp",
            "app/services",
            "docs",
        ],
        "required_doc_path_mentions": {},
        "documented_endpoint_modules": [],
        "documented_service_modules": [],
        "documented_mcp_modules": [],
    }
    (tmp_path / "docs" / "repo-contract.json").write_text(json.dumps(contract))

    errors = validate_repo(tmp_path)

    assert any("Undocumented endpoint modules: sample" in error for error in errors)
