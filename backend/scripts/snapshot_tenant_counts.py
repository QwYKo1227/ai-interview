"""Snapshot and compare all authoritative tenant-table row counts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Iterable

from sqlalchemy import create_engine, inspect, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.tenant_catalog import TENANT_TABLES


SCHEMA = "ai-interview.tenant-table-counts"
VERSION = 1


def snapshot_tenant_counts(db) -> dict:
    bind = db.get_bind() if hasattr(db, "get_bind") else db
    existing = set(inspect(bind).get_table_names())
    tables = {}
    for table in TENANT_TABLES:
        present = table in existing
        rows = (
            int(db.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one())
            if present
            else 0
        )
        tables[table] = {"present": present, "rows": rows}
    return {"schema": SCHEMA, "version": VERSION, "tables": tables}


def compare_tenant_count_snapshots(
    before: dict,
    after: dict,
    *,
    allowed_stored_files_increase: int = 0,
) -> dict:
    expected_tables = list(TENANT_TABLES)
    if (
        before.get("schema") != SCHEMA
        or after.get("schema") != SCHEMA
        or before.get("version") != VERSION
        or after.get("version") != VERSION
        or list(before.get("tables", {})) != expected_tables
        or list(after.get("tables", {})) != expected_tables
        or isinstance(allowed_stored_files_increase, bool)
        or not isinstance(allowed_stored_files_increase, int)
        or allowed_stored_files_increase < 0
    ):
        return {
            "schema": "ai-interview.tenant-table-count-comparison",
            "version": VERSION,
            "ok": False,
            "differences": {"contract": {"status": "invalid_snapshot"}},
        }

    differences = {}
    for table in TENANT_TABLES:
        old = int(before["tables"][table]["rows"])
        new = int(after["tables"][table]["rows"])
        expected_increase = (
            allowed_stored_files_increase if table == "stored_files" else 0
        )
        if not after["tables"][table]["present"]:
            status = "table_missing_after"
        elif new < old:
            status = "decreased"
        elif new - old > expected_increase:
            status = "unexpected_increase"
        elif new - old < expected_increase:
            status = "stored_file_increase_mismatch"
        elif new > old:
            status = "expected_increase"
        else:
            continue
        differences[table] = {"before": old, "after": new, "status": status}

    blocking = {
        "decreased",
        "unexpected_increase",
        "stored_file_increase_mismatch",
        "table_missing_after",
    }
    return {
        "schema": "ai-interview.tenant-table-count-comparison",
        "version": VERSION,
        "ok": not any(item["status"] in blocking for item in differences.values()),
        "differences": differences,
    }


def _atomic_text(path: Path, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="")
    temporary.replace(path)


def write_snapshot_files(snapshot: dict, *, json_path: Path, csv_path: Path) -> None:
    _atomic_text(
        Path(json_path),
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
    )
    rows = ["table,present,rows"]
    for table, item in snapshot["tables"].items():
        rows.append(f'{table},{str(bool(item["present"])).lower()},{int(item["rows"])}')
    _atomic_text(Path(csv_path), "\n".join(rows) + "\n")


def _snapshot_from_postgres(url: str) -> dict:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                if connection.dialect.name == "postgresql":
                    role = connection.execute(text("SELECT current_user")).scalar_one()
                    if role != "app_migration":
                        raise RuntimeError("migration role required")
                    existing = set(inspect(connection).get_table_names())
                    connection.execute(text("SET LOCAL lock_timeout = '5s'"))
                    connection.execute(text("SET LOCAL statement_timeout = '60s'"))
                    for table in TENANT_TABLES:
                        if table in existing:
                            connection.execute(
                                text(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
                            )
                return snapshot_tenant_counts(connection)
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def run_cli(argv: Iterable[str] | None = None, *, environ=None, stdout=None) -> int:
    parser = argparse.ArgumentParser(description="Snapshot or compare tenant counts")
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--json", required=True, type=Path)
    snapshot_parser.add_argument("--csv", required=True, type=Path)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--before", required=True, type=Path)
    compare_parser.add_argument("--after", required=True, type=Path)
    compare_parser.add_argument(
        "--allow-stored-files-increase",
        type=int,
        default=0,
    )
    args = parser.parse_args(argv)
    environ = os.environ if environ is None else environ
    stdout = sys.stdout if stdout is None else stdout

    try:
        if args.command == "snapshot":
            url = environ.get("MIGRATION_DATABASE_URL")
            if not url:
                raise RuntimeError("migration URL required")
            snapshot = _snapshot_from_postgres(url)
            write_snapshot_files(snapshot, json_path=args.json, csv_path=args.csv)
            result = {"ok": True, "tables": len(snapshot["tables"])}
        else:
            before = json.loads(args.before.read_text(encoding="utf-8"))
            after = json.loads(args.after.read_text(encoding="utf-8"))
            result = compare_tenant_count_snapshots(
                before,
                after,
                allowed_stored_files_increase=args.allow_stored_files_increase,
            )
    except Exception:
        result = {"ok": False, "error": "tenant count operation failed"}
    print(json.dumps(result, sort_keys=True), file=stdout)
    return 0 if result["ok"] else 1


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
