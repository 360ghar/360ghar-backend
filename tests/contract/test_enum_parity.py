"""Enum parity: stored labels equal Python values, and schemas reuse app.models.enums.

The database check is skipped unless CONTRACT_DRIFT_DATABASE_URL is set.
The static checks always run.
"""

from __future__ import annotations

import ast
import os
from enum import Enum
from pathlib import Path

import pytest
import sqlalchemy as sa

import app
import app.models  # noqa: F401  (registers every mapped table on Base.metadata)
from app.core.database import Base
from app.models import enums as enums_module

DRIFT_URL = os.environ.get("CONTRACT_DRIFT_DATABASE_URL")
SCHEMAS_DIR = Path(app.__file__).resolve().parent / "schemas"


def _db_enum_columns() -> list[tuple[str, sa.Column]]:
    """Every native enum column in the models, with its table name."""
    columns = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, sa.Enum) and col.type.native_enum:
                columns.append((table.name, col))
    return columns


def _canonical_enums() -> dict[str, type[Enum]]:
    return {
        name: obj
        for name, obj in vars(enums_module).items()
        if isinstance(obj, type)
        and issubclass(obj, Enum)
        and obj.__module__ == enums_module.__name__
    }


def test_every_native_enum_column_stores_values() -> None:
    """Each enum column writes member values, not member names (see db_enum)."""
    columns = _db_enum_columns()
    assert columns, "expected native enum columns in the models"
    for table_name, col in columns:
        enum_cls = col.type.enum_class
        assert enum_cls is not None, f"{table_name}.{col.name} has no enum class"
        assert col.type.values_callable is not None, (
            f"{table_name}.{col.name} must use db_enum() so the DB stores values"
        )
        stored = col.type.values_callable(enum_cls)
        assert list(stored) == [m.value for m in enum_cls], f"{table_name}.{col.name}"


@pytest.mark.skipif(not DRIFT_URL, reason="CONTRACT_DRIFT_DATABASE_URL is not set")
def test_db_enum_labels_match_python_values() -> None:
    import psycopg

    from scripts.verify_schema_drift import psycopg_url

    assert DRIFT_URL is not None
    with psycopg.connect(psycopg_url(DRIFT_URL)) as conn:
        rows = conn.execute(
            "SELECT t.typname, e.enumlabel FROM pg_type t "
            "JOIN pg_enum e ON e.enumtypid = t.oid "
            "JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'public'"
        ).fetchall()
    labels: dict[str, set[str]] = {}
    for type_name, label in rows:
        labels.setdefault(type_name, set()).add(label)

    problems = []
    for table_name, col in _db_enum_columns():
        wanted = {m.value for m in col.type.enum_class}
        have = labels.get(col.type.name)
        if have is None:
            problems.append(f"{table_name}.{col.name}: DB type {col.type.name} is missing")
        elif have != wanted:
            problems.append(f"{table_name}.{col.name}: db={sorted(have)} python={sorted(wanted)}")
    assert not problems, "enum labels differ from Python values:\n" + "\n".join(problems)


def test_schemas_do_not_redefine_canonical_enums() -> None:
    """An enum name from app/models/enums.py must not be defined again under app/schemas."""
    canonical = set(_canonical_enums())
    offenders = []
    for path in sorted(SCHEMAS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in canonical:
                offenders.append(
                    f"{path.relative_to(SCHEMAS_DIR.parent)}:{node.lineno} {node.name}"
                )
    assert not offenders, "import the enum from app.models.enums instead:\n" + "\n".join(offenders)


def test_schemas_do_not_copy_enum_value_sets_as_literals() -> None:
    """A Literal in app/schemas that lists exactly an enum's values is a copy of that enum."""
    value_sets = {
        frozenset(m.value for m in enum_cls): name for name, enum_cls in _canonical_enums().items()
    }
    offenders = []
    for path in sorted(SCHEMAS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)):
                continue
            if node.value.id != "Literal":
                continue
            elts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            if not elts or not all(
                isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elts
            ):
                continue
            values = frozenset(e.value for e in elts)
            if values in value_sets:
                offenders.append(
                    f"{path.relative_to(SCHEMAS_DIR.parent)}:{node.lineno} "
                    f"Literal duplicates {value_sets[values]}"
                )
    assert not offenders, "use the enum type, not a Literal copy:\n" + "\n".join(offenders)
