"""Safely inventory, verify, or backfill pre-tenant files.

The command never deletes legacy files.  It copies each file to a tenant UUID
object key through a ``.part`` file, atomically renames it, then commits the
``StoredFile`` row and resource link.  A database failure removes the new copy.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Iterable
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config.tenant_session import TenantCapableSession, TenantSession
from app.models.file_models import StoredFile
from app.models.models import Interview, InterviewPanel, QuestionBank, Resume
from app.models.tenant_models import Tenant
from app.utils.legacy_uploads import (
    LegacyUploadPathError,
    is_legacy_file_reference,
    iter_legacy_file_references,
    resolve_legacy_upload_source,
)
from app.utils.file_storage import (
    SAFE_EXTENSION,
    resolve_object_path,
    sanitize_content_type,
)


class LegacyFileError(ValueError):
    """A safe, non-secret legacy-file validation error."""


@dataclass(frozen=True)
class LegacyFileCandidate:
    table: str
    row_id: UUID
    tenant_id: UUID
    legacy_path: str
    path_field: str
    file_id_field: str | None
    category: str
    resource_type: str
    json_path: tuple[str | int, ...] = ()


@dataclass(frozen=True)
class BackfillItemResult:
    table: str
    row_id: str
    tenant_id: str
    status: str
    file_id: str | None = None


_MODEL_BY_TABLE = {
    "resumes": Resume,
    "question_banks": QuestionBank,
    "interviews": Interview,
    "interview_panels": InterviewPanel,
}


def _result(candidate: LegacyFileCandidate, status: str, file_id=None):
    return BackfillItemResult(
        table=candidate.table,
        row_id=str(candidate.row_id),
        tenant_id=str(candidate.tenant_id),
        status=status,
        file_id=str(file_id) if file_id else None,
    )


def _json_value(value, path: tuple[str | int, ...]):
    current = value
    for part in path:
        current = current[part]
    return current


def _replace_json_value(value, path: tuple[str | int, ...], replacement: str):
    copied = json.loads(json.dumps(value))
    current = copied
    for part in path[:-1]:
        current = current[part]
    current[path[-1]] = replacement
    return copied


def _record_state(db: Session, candidate: LegacyFileCandidate):
    model = _MODEL_BY_TABLE.get(candidate.table)
    if model is None:
        raise LegacyFileError("unsupported legacy resource table")
    record = db.get(model, candidate.row_id)
    if record is None or record.tenant_id != candidate.tenant_id:
        raise LegacyFileError("legacy resource is missing or belongs to another tenant")
    value = getattr(record, candidate.path_field)
    if candidate.json_path:
        try:
            value = _json_value(value, candidate.json_path)
        except (KeyError, IndexError, TypeError):
            raise LegacyFileError("legacy file reference changed during migration") from None
    file_id = (
        getattr(record, candidate.file_id_field)
        if candidate.file_id_field
        else None
    )
    return record, value, file_id


def _validated_source(candidate: LegacyFileCandidate, legacy_root: Path) -> Path:
    try:
        return resolve_legacy_upload_source(
            legacy_root,
            candidate.legacy_path,
            tenant_id=candidate.tenant_id,
        )
    except LegacyUploadPathError as exc:
        raise LegacyFileError(str(exc)) from None


def backfill_candidate(
    db: Session,
    candidate: LegacyFileCandidate,
    *,
    legacy_root: Path,
    upload_root: Path,
    dry_run: bool = False,
) -> BackfillItemResult:
    """Backfill one candidate, preserving the source and compensating failures."""

    record, current_value, current_file_id = _record_state(db, candidate)
    if current_file_id is not None or (
        isinstance(current_value, str) and current_value.startswith("/api/files/")
    ):
        if current_file_id is not None:
            stored = db.get(StoredFile, current_file_id)
            if stored is None or stored.tenant_id != candidate.tenant_id:
                raise LegacyFileError("existing file link belongs to another tenant")
        db.rollback()
        return _result(candidate, "already_migrated", current_file_id)
    if current_value != candidate.legacy_path:
        db.rollback()
        raise LegacyFileError("legacy file reference changed during migration")

    source = _validated_source(candidate, Path(legacy_root))
    if dry_run:
        db.rollback()
        return _result(candidate, "would_migrate")

    file_id = uuid4()
    suffix = source.suffix.lower() if SAFE_EXTENSION.fullmatch(source.suffix) else ""
    object_key = f"{candidate.tenant_id}/{candidate.category}/{uuid4()}{suffix}"
    final_path = resolve_object_path(Path(upload_root), candidate.tenant_id, object_key)
    partial_path = final_path.with_name(final_path.name + ".part")
    try:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as source_handle, partial_path.open("xb") as target:
            shutil.copyfileobj(source_handle, target, length=1024 * 1024)
        if partial_path.stat().st_size == 0:
            raise LegacyFileError("legacy file is empty")
        partial_path.replace(final_path)

        stored = StoredFile(
            id=file_id,
            tenant_id=candidate.tenant_id,
            object_key=object_key,
            original_filename=source.name[:255] or "upload",
            content_type=sanitize_content_type(source.name),
            size=final_path.stat().st_size,
            category=candidate.category,
            resource_type=candidate.resource_type,
            resource_id=candidate.row_id,
        )
        db.add(stored)
        if candidate.json_path:
            setattr(
                record,
                candidate.path_field,
                _replace_json_value(
                    getattr(record, candidate.path_field),
                    candidate.json_path,
                    f"/api/files/{file_id}",
                ),
            )
        else:
            setattr(record, candidate.path_field, f"/api/files/{file_id}")
        if candidate.file_id_field:
            setattr(record, candidate.file_id_field, file_id)
        db.commit()
    except Exception:
        db.rollback()
        partial_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise
    return _result(candidate, "migrated", file_id)


def discover_legacy_candidates(db: Session) -> list[LegacyFileCandidate]:
    """Inventory legacy references visible in one tenant-scoped session."""

    candidates = []
    for record in db.query(Resume).filter(Resume.file_id.is_(None)).all():
        if is_legacy_file_reference(record.file_path):
            candidates.append(
                LegacyFileCandidate(
                    "resumes", record.id, record.tenant_id, record.file_path,
                    "file_path", "file_id", "resumes", "resume"
                )
            )
    for record in db.query(QuestionBank).filter(QuestionBank.source_file_id.is_(None)).all():
        if is_legacy_file_reference(record.source_file):
            candidates.append(
                LegacyFileCandidate(
                    "question_banks", record.id, record.tenant_id,
                    record.source_file, "source_file", "source_file_id",
                    "question_banks", "question_bank"
                )
            )
    for model, table, resource_type in (
        (Interview, "interviews", "interview"),
        (InterviewPanel, "interview_panels", "interview_panel"),
    ):
        for record in db.query(model).all():
            for json_path, legacy_path in iter_legacy_file_references(
                record.audio_records
            ):
                candidates.append(
                    LegacyFileCandidate(
                        table, record.id, record.tenant_id, legacy_path,
                        "audio_records", None, "interview_audio", resource_type,
                        json_path,
                    )
                )
    return sorted(
        candidates,
        key=lambda item: (item.table, str(item.tenant_id), str(item.row_id), item.json_path),
    )


def _require_migration_role(db: Session) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    role = db.execute(text("SELECT current_user")).scalar_one()
    if role != "app_migration":
        raise LegacyFileError("the backfill must run as app_migration")


def run_cli(mode: str, *, dry_run: bool = False, environ=None, stdout=None) -> int:
    environ = os.environ if environ is None else environ
    stdout = sys.stdout if stdout is None else stdout
    url = environ.get("MIGRATION_DATABASE_URL")
    if not url:
        print(json.dumps({"ok": False, "error": "MIGRATION_DATABASE_URL is required"}), file=stdout)
        return 1
    legacy_root = Path(environ.get("LEGACY_UPLOAD_ROOT", "uploads"))
    upload_root = Path(environ.get("UPLOAD_ROOT", "uploads"))
    engine = None
    try:
        engine = create_engine(url)
        unscoped = TenantCapableSession(bind=engine)
        try:
            _require_migration_role(unscoped)
            tenant_ids = [row[0] for row in unscoped.query(Tenant.id).order_by(Tenant.id).all()]
        finally:
            unscoped.close()

        results = []
        errors = 0
        factory = sessionmaker(bind=engine, class_=TenantSession, expire_on_commit=False)
        for tenant_id in tenant_ids:
            tenant_db = factory(tenant_id=tenant_id)
            try:
                candidates = discover_legacy_candidates(tenant_db)
                tenant_db.rollback()
                for candidate in candidates:
                    try:
                        item = backfill_candidate(
                            tenant_db,
                            candidate,
                            legacy_root=legacy_root,
                            upload_root=upload_root,
                            dry_run=dry_run or mode in {"inventory", "verify"},
                        )
                        results.append(asdict(item))
                    except Exception:
                        tenant_db.rollback()
                        errors += 1
                        results.append(asdict(_result(candidate, "error")))
            finally:
                tenant_db.close()
        pending = sum(item["status"] == "would_migrate" for item in results)
        ok = errors == 0 and (mode != "verify" or pending == 0)
        payload = {
            "schema": "ai-interview.legacy-upload-backfill",
            "version": 1,
            "ok": ok,
            "mode": mode,
            "dry_run": dry_run,
            "counts": {"candidates": len(results), "pending": pending, "errors": errors},
            "items": results,
        }
        print(json.dumps(payload, sort_keys=True), file=stdout)
        return 0 if ok else 1
    except Exception:
        print(json.dumps({"ok": False, "error": "legacy upload backfill failed"}), file=stdout)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory or backfill legacy uploads")
    parser.add_argument("mode", choices=("inventory", "verify", "migrate"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return run_cli(args.mode, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
