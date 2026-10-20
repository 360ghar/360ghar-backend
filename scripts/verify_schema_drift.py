#!/usr/bin/env python3
"""Verify SQLAlchemy models against a migrated database schema (full parity).

Compares the ``app.models`` Base metadata with the database in the ``public``
schema. Checks, per model table that exists in the database:

- every model column exists (missing column: error)
- column type family (varchar length, numeric precision/scale, timestamptz vs
  timestamp, boolean, integer widths, double vs real, json vs jsonb, enums)
- nullability
- enum label sets: DB labels equal the Python enum values (db_enum columns)
- CHECK ``col IN (...)`` label lists (string-stored enums)
- unique constraints and unique indexes, including partial ones
- foreign key targets and ON DELETE rules

A model table missing from the database fails the check, unless it is listed
in ``MISSING_TABLE_EXEMPTIONS`` with a reason. Database columns that the model
does not define are reported. A NOT NULL column without a default fails the
check. Other extra columns are notes only.

Known differences that other work will fix live in
``scripts/schema_drift_allowlist.txt``, one line per difference::

    table.column: kind: detail

Any difference not in the allowlist fails the check. An allowlist line that no
longer matches a real difference also fails, so the list shrinks as fixes land.

Usage:
    uv run python scripts/verify_schema_drift.py                 # DATABASE_URL from env
    uv run python scripts/verify_schema_drift.py --env .env.prod
    uv run python scripts/verify_schema_drift.py --write-allowlist   # regenerate the list
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple

import sqlalchemy as sa
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from run_supabase_migrations import _normalise_database_url
except ImportError:  # imported as ``scripts.verify_schema_drift``
    from scripts.run_supabase_migrations import _normalise_database_url

DEFAULT_ALLOWLIST = Path(__file__).resolve().parent / "schema_drift_allowlist.txt"
_FK_RULES = {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT"}
_CHECK_IN_RE = re.compile(r"^\s*(\w+) IN \((.*)\)\s*$")
_QUOTED_RE = re.compile(r"'([^']*)'")

# Model tables that no migration creates. Each entry needs a reason. An entry
# fails the check once its table exists in the database, or when no model
# defines it, so the list shrinks as the tables are dealt with.
MISSING_TABLE_EXEMPTIONS: dict[str, str] = {
}


# ── Model side ───────────────────────────────────────────────────────────────


def _model_family(col: Any) -> tuple[str | None, dict[str, int | None]]:
    """Map a model column type to a comparable family. None means unchecked."""
    from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
    from sqlalchemy.dialects.postgresql import UUID as PgUUID
    from sqlalchemy.types import TypeDecorator

    t = col.type
    if isinstance(t, TypeDecorator):
        t = t.impl
    if isinstance(t, sa.Enum):
        if t.native_enum and t.name:
            return t.name, {}
        return "varchar", {"length": t.length}
    if isinstance(t, JSONB):
        return "jsonb", {}
    if isinstance(t, sa.JSON):
        return "json", {}
    if isinstance(t, (sa.Uuid, PgUUID)):
        return "uuid", {}
    if isinstance(t, TSVECTOR):
        return "tsvector", {}
    if isinstance(t, sa.ARRAY):
        return "array", {}
    if isinstance(t, sa.Boolean):
        return "boolean", {}
    if isinstance(t, sa.DateTime):
        return ("timestamptz" if t.timezone else "timestamp"), {}
    if isinstance(t, sa.Date):
        return "date", {}
    if isinstance(t, sa.Time):
        return "time", {}
    if isinstance(t, sa.Float):
        return ("real" if t.precision is not None and t.precision <= 24 else "double"), {}
    if isinstance(t, sa.Numeric):
        return "numeric", {"precision": t.precision, "scale": t.scale}
    if isinstance(t, sa.BigInteger):  # subclasses of Integer, so test first
        return "int8", {}
    if isinstance(t, sa.SmallInteger):
        return "int2", {}
    if isinstance(t, sa.Integer):
        return "int4", {}
    if isinstance(t, sa.Text):
        return "text", {}
    if isinstance(t, sa.String):
        return "varchar", {"length": t.length}
    type_name = type(t).__name__.lower()
    if type_name in ("geography", "geometry", "vector"):  # geoalchemy2 / pgvector
        return type_name, {}
    return None, {}


def _model_unique_keys(table: Any) -> set[tuple[tuple[str, ...], bool]]:
    keys: set[tuple[tuple[str, ...], bool]] = set()
    for constraint in table.constraints:
        if constraint.__class__.__name__ == "UniqueConstraint":
            keys.add((tuple(sorted(c.name for c in constraint.columns)), False))
    for index in table.indexes:
        if not index.unique:
            continue
        if any(not hasattr(expr, "name") for expr in index.expressions):
            continue  # expression indexes are out of scope
        partial = index.dialect_options["postgresql"].get("where") is not None
        keys.add((tuple(sorted(c.name for c in index.columns)), partial))
    for col in table.columns:
        if col.unique and not col.primary_key:
            keys.add(((col.name,), False))
    return keys


def _model_fk_keys(table: Any) -> dict[tuple[str, ...], tuple[str, str]]:
    result: dict[tuple[str, ...], tuple[str, str]] = {}
    for fkc in table.foreign_key_constraints:
        cols = tuple(sorted(e.parent.name for e in fkc.elements))
        target = fkc.referred_table.name
        rule = (fkc.ondelete or "NO ACTION").upper()
        result[cols] = (target, rule)
    return result


def _model_checks(table: Any) -> dict[str, tuple[str, list[str]]]:
    """CHECK ``col IN (...)`` constraints keyed by constraint name."""
    result: dict[str, tuple[str, list[str]]] = {}
    for constraint in table.constraints:
        if constraint.__class__.__name__ != "CheckConstraint" or not constraint.name:
            continue
        match = _CHECK_IN_RE.match(str(constraint.sqltext))
        if match:
            values = _QUOTED_RE.findall(match.group(2))
            result[constraint.name] = (match.group(1), values)
    return result


# ── Database side ────────────────────────────────────────────────────────────


def _db_family(data_type: str, udt: str) -> str:
    mapping = {
        "character varying": "varchar",
        "text": "text",
        "timestamp with time zone": "timestamptz",
        "timestamp without time zone": "timestamp",
        "date": "date",
        "time without time zone": "time",
        "integer": "int4",
        "bigint": "int8",
        "smallint": "int2",
        "boolean": "boolean",
        "numeric": "numeric",
        "double precision": "double",
        "real": "real",
        "json": "json",
        "jsonb": "jsonb",
        "uuid": "uuid",
        "ARRAY": "array",
        "tsvector": "tsvector",
    }
    if data_type == "USER-DEFINED":
        return udt  # enum type name, or geography / geometry / vector
    return mapping.get(data_type, data_type)


def _fmt(values: list[str] | set[str]) -> str:
    return ",".join(sorted(values)) if values else "-"


def _length(length: int | None) -> str:
    return "unbounded" if length is None else str(length)


def _numeric_spec(precision: int | None, scale: int | None) -> str:
    """Render numeric(p,s). A numeric without precision is unbounded."""
    if precision is None:
        return "unbounded"
    return f"{precision},{scale or 0}"


def _collect_db(cur: Any, table_names: list[str]) -> dict[str, Any]:
    cur.execute(
        "SELECT table_name, column_name, data_type, udt_name, is_nullable, "
        "character_maximum_length, numeric_precision, numeric_scale, "
        "column_default, is_identity, is_generated "
        "FROM information_schema.columns WHERE table_schema = 'public' "
        "AND table_name = ANY(%s)",
        (table_names,),
    )
    columns: dict[tuple[str, str], dict[str, Any]] = {}
    tables: set[str] = set()
    for row in cur.fetchall():
        table, column, data_type, udt, nullable, char_len, prec, scale, default, identity, gen = row
        tables.add(table)
        columns[(table, column)] = {
            "family": _db_family(data_type, udt),
            "nullable": nullable == "YES",
            "length": char_len,
            "precision": prec,
            "scale": scale,
            "has_default": default is not None or identity == "YES" or gen == "ALWAYS",
        }

    cur.execute(
        "SELECT t.typname, e.enumlabel FROM pg_type t "
        "JOIN pg_enum e ON e.enumtypid = t.oid "
        "JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'public'"
    )
    enum_labels: dict[str, set[str]] = {}
    for type_name, label in cur.fetchall():
        enum_labels.setdefault(type_name, set()).add(label)

    cur.execute(
        "SELECT t.relname, i.indpred IS NOT NULL, "
        "ARRAY(SELECT a.attname FROM pg_attribute a "
        "      WHERE a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey::int2[])) "
        "FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid "
        "JOIN pg_namespace n ON n.oid = t.relnamespace "
        "WHERE n.nspname = 'public' AND i.indisunique AND NOT i.indisprimary"
    )
    unique: dict[str, set[tuple[tuple[str, ...], bool]]] = {}
    for table, partial, cols in cur.fetchall():
        unique.setdefault(table, set()).add((tuple(sorted(cols)), bool(partial)))

    cur.execute(
        "SELECT t.relname, ARRAY(SELECT a.attname FROM pg_attribute a "
        "  JOIN unnest(c.conkey) AS k(attnum) ON k.attnum = a.attnum "
        "  WHERE a.attrelid = c.conrelid), rt.relname, c.confdeltype "
        "FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
        "JOIN pg_class rt ON rt.oid = c.confrelid "
        "JOIN pg_namespace n ON n.oid = t.relnamespace "
        "WHERE c.contype = 'f' AND n.nspname = 'public'"
    )
    fks: dict[str, dict[tuple[str, ...], tuple[str, str]]] = {}
    for table, cols, target, rule in cur.fetchall():
        fks.setdefault(table, {})[tuple(sorted(cols))] = (target, _FK_RULES.get(rule, rule))

    cur.execute(
        "SELECT t.relname, c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace "
        "WHERE c.contype = 'c' AND n.nspname = 'public'"
    )
    checks: dict[str, tuple[str, str]] = {}
    for table, name, definition in cur.fetchall():
        checks[name] = (table, definition)

    return {
        "tables": tables,
        "columns": columns,
        "enum_labels": enum_labels,
        "unique": unique,
        "fks": fks,
        "checks": checks,
    }


def _check_table(table: Any, db: dict[str, Any]) -> list[str]:
    """Return difference lines ``table.column: kind: detail`` for one table."""
    diffs: list[str] = []
    name = table.name
    for col in table.columns:
        key = f"{name}.{col.name}"
        db_col = db["columns"].get((name, col.name))
        if db_col is None:
            diffs.append(f"{key}: missing_column: not in database")
            continue

        family, info = _model_family(col)
        if family is not None:
            ok = family == db_col["family"]
            if family == "varchar" and info.get("length") is None:
                ok = ok or db_col["family"] == "text"  # unbounded varchar is text in PostgreSQL
            if not ok:
                diffs.append(f"{key}: type: model={family} db={db_col['family']}")
            elif family == "varchar" and db_col["family"] == "varchar":
                want_len, got_len = info.get("length"), db_col["length"]
                if want_len != got_len:
                    diffs.append(
                        f"{key}: type: varchar length model={_length(want_len)} db={_length(got_len)}"
                    )
            elif family == "numeric":
                want = _numeric_spec(info["precision"], info["scale"])
                got = _numeric_spec(db_col["precision"], db_col["scale"])
                if want != got:
                    diffs.append(f"{key}: type: numeric model={want} db={got}")

        if col.nullable != db_col["nullable"]:
            diffs.append(
                f"{key}: nullable: model={'NULL' if col.nullable else 'NOT NULL'} "
                f"db={'NULL' if db_col['nullable'] else 'NOT NULL'}"
            )

        if (
            isinstance(col.type, sa.Enum)
            and col.type.native_enum
            and col.type.enum_class is not None
            and db_col["family"] == col.type.name
        ):
            wanted = {member.value for member in col.type.enum_class}
            have = db["enum_labels"].get(col.type.name, set())
            if wanted != have:
                diffs.append(
                    f"{key}: enum_labels: missing_in_db={_fmt(wanted - have)} "
                    f"extra_in_db={_fmt(have - wanted)}"
                )

    model_unique = _model_unique_keys(table)
    db_unique = db["unique"].get(name, set())
    for cols, partial in sorted(model_unique - db_unique):
        kind = "partial" if partial else "full"
        diffs.append(f"{name}.{'+'.join(cols)}: unique: missing_in_db {kind}")
    for cols, partial in sorted(db_unique - model_unique):
        kind = "partial" if partial else "full"
        diffs.append(f"{name}.{'+'.join(cols)}: unique: extra_in_db {kind}")

    model_fks = _model_fk_keys(table)
    db_fks = db["fks"].get(name, {})
    for cols in sorted(set(model_fks) | set(db_fks)):
        want = model_fks.get(cols)
        have = db_fks.get(cols)
        label = f"{name}.{'+'.join(cols)}"
        if want is None:
            diffs.append(f"{label}: fk: extra_in_db target={have[0]} on_delete={have[1]}")
        elif have is None:
            diffs.append(f"{label}: fk: missing_in_db target={want[0]} on_delete={want[1]}")
        elif want != have:
            diffs.append(
                f"{label}: fk: model={want[0]} on_delete={want[1]} db={have[0]} on_delete={have[1]}"
            )

    for check_name, (col_name, values) in _model_checks(table).items():
        found = db["checks"].get(check_name)
        if found is None:
            diffs.append(f"{name}.{col_name}: check_missing: name={check_name}")
            continue
        db_values = set(_QUOTED_RE.findall(found[1]))
        wanted = set(values)
        if wanted != db_values:
            diffs.append(
                f"{name}.{col_name}: check_labels: missing_in_db={_fmt(wanted - db_values)} "
                f"extra_in_db={_fmt(db_values - wanted)}"
            )
    return diffs


def psycopg_url(url: str) -> str:
    """Accept SQLAlchemy-style URLs (``postgresql+psycopg://``) as well as libpq URLs."""
    return _normalise_database_url(re.sub(r"^postgres(ql)?\+\w+://", "postgresql://", url))


class Drift(NamedTuple):
    diffs: list[str]  # must be in the allowlist
    errors: list[str]  # never allowlisted: fix the exemption list
    notes: list[str]  # printed only


def _table_presence(
    model_tables: list[str], db_tables: set[str]
) -> tuple[list[str], list[str], list[str]]:
    """Return ``(diffs, errors, notes)`` for model tables that are absent or exempt."""
    diffs: list[str] = []
    errors: list[str] = []
    notes: list[str] = []
    for name in sorted(set(MISSING_TABLE_EXEMPTIONS) - set(model_tables)):
        errors.append(
            f"{name}: exemption_unknown: no model defines this table; "
            "remove it from MISSING_TABLE_EXEMPTIONS"
        )
    for name in model_tables:
        exempt = MISSING_TABLE_EXEMPTIONS.get(name)
        if name in db_tables:
            if exempt is not None:
                errors.append(
                    f"{name}: exemption_stale: table exists in the database; "
                    "remove it from MISSING_TABLE_EXEMPTIONS"
                )
        elif exempt is None:
            diffs.append(f"{name}: table_missing: not in database")
        else:
            notes.append(f"{name}: not in database (exempt: {exempt})")
    return diffs, errors, notes


def _extra_column_lines(
    table_name: str, model_columns: set[str], db: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Return ``(diffs, notes)`` for database columns the model does not define."""
    diffs: list[str] = []
    notes: list[str] = []
    for (table, column), info in db["columns"].items():
        if table != table_name or column in model_columns:
            continue
        key = f"{table}.{column}"
        if info["nullable"] or info["has_default"]:
            notes.append(f"{key}: extra_column: not in model (nullable or has default)")
        else:
            diffs.append(f"{key}: extra_column: not_null_without_default")
    return diffs, notes


def collect_drift(database_url: str) -> Drift:
    """Compare the models with the database. See ``Drift`` for the three lists."""
    import psycopg

    from app.core.database import Base

    table_names = sorted(Base.metadata.tables)
    with psycopg.connect(psycopg_url(database_url)) as conn:
        with conn.cursor() as cur:
            db = _collect_db(cur, table_names)

    diffs, errors, notes = _table_presence(table_names, db["tables"])
    for table_name in table_names:
        if table_name not in db["tables"]:
            continue
        table = Base.metadata.tables[table_name]
        diffs.extend(_check_table(table, db))
        extra_diffs, extra_notes = _extra_column_lines(
            table_name, {col.name for col in table.columns}, db
        )
        diffs.extend(extra_diffs)
        notes.extend(extra_notes)
    return Drift(diffs, errors, notes)


def load_allowlist(path: Path) -> list[str]:
    if not path.is_file():
        return []
    entries = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            entries.append(line)
    return entries


def check_drift(*, database_url: str, allowlist: Path = DEFAULT_ALLOWLIST) -> list[str]:
    """Return problem lines. An empty list means parity holds (after the allowlist)."""
    drift = collect_drift(database_url)
    allowed = set(load_allowlist(allowlist))
    problems = [f"not in allowlist: {d}" for d in drift.diffs if d not in allowed]
    problems += drift.errors
    problems += [
        f"stale allowlist entry (remove it): {a}" for a in sorted(allowed - set(drift.diffs))
    ]
    return problems


def verify_schema_drift(*, env_file: str | None = None, write_allowlist: bool = False) -> int:
    env_path = Path(env_file) if env_file else None
    if env_path is not None:
        if not env_path.is_file():
            print(f"ERROR: Env file not found: {env_path}", file=sys.stderr)
            return 1
        load_dotenv(env_path)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print(
            "ERROR: DATABASE_URL environment variable is not set.\n"
            "Set it in your shell or pass --env with a file that sets it.",
            file=sys.stderr,
        )
        return 1

    try:
        import app.models  # noqa: F401  (registers every mapped table on Base.metadata)
    except Exception as exc:
        print(
            f"ERROR: failed to load SQLAlchemy models (missing env vars?): {exc}",
            file=sys.stderr,
        )
        return 1

    drift = collect_drift(database_url)
    if drift.notes:
        print("NOTE: not gating (review when touching these tables):")
        for line in drift.notes:
            print(f"  - {line}")

    if write_allowlist:
        header = (
            "# Known schema drift between app/models and the migrated database.\n"
            "# One line per difference: table.column: kind: detail\n"
            "# Remove a line when its difference is fixed. Regenerate with:\n"
            "#   uv run python scripts/verify_schema_drift.py --write-allowlist\n"
        )
        DEFAULT_ALLOWLIST.write_text(header + "\n".join(sorted(set(drift.diffs))) + "\n")
        print(f"Wrote {len(set(drift.diffs))} entries to {DEFAULT_ALLOWLIST}")
        if drift.errors:
            print("ERROR: fix MISSING_TABLE_EXEMPTIONS:")
            for line in drift.errors:
                print(f"  - {line}")
            return 1
        return 0

    allowed = set(load_allowlist(DEFAULT_ALLOWLIST))
    unknown = [d for d in drift.diffs if d not in allowed]
    stale = sorted(allowed - set(drift.diffs))
    if drift.errors:
        print("ERROR: MISSING_TABLE_EXEMPTIONS is out of date:")
        for line in drift.errors:
            print(f"  - {line}")
    if unknown:
        print("ERROR: schema drift not in scripts/schema_drift_allowlist.txt:")
        for line in unknown:
            print(f"  - {line}")
    if stale:
        print("ERROR: allowlist entries that no longer match (remove them):")
        for line in stale:
            print(f"  - {line}")
    if drift.errors or unknown or stale:
        return 1

    print(f"OK: models match the database (allowlisted differences: {len(drift.diffs)}).")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check SQLAlchemy models against the migrated database schema.",
    )
    parser.add_argument(
        "--env",
        default=None,
        help=".env file to load DATABASE_URL from (default: environment only)",
    )
    parser.add_argument(
        "--write-allowlist",
        action="store_true",
        help="Rewrite scripts/schema_drift_allowlist.txt from the current differences",
    )
    args = parser.parse_args()
    sys.exit(verify_schema_drift(env_file=args.env, write_allowlist=args.write_allowlist))


if __name__ == "__main__":
    main()
