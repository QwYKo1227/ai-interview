import os
import re
import logging
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from fastapi import UploadFile

from app.models.file_models import StoredFile

logger = logging.getLogger(__name__)


UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", "uploads"))
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(50 * 1024 * 1024)))
ALLOWED_CATEGORIES = frozenset(
    {"resumes", "question_banks", "interview_audio", "coding_attachments", "offers"}
)
SAFE_EXTENSION = re.compile(r"^\.[A-Za-z0-9]{1,10}$")
FILE_DOWNLOAD_URL = re.compile(r"^/api/files/([0-9a-fA-F-]{36})$")
SAFE_MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".webm": "audio/webm",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
}


def _validated_category(category: str) -> str:
    if category not in ALLOWED_CATEGORIES or not re.fullmatch(r"[a-z0-9_]+", category or ""):
        raise ValueError("invalid file category")
    return category


def _safe_original_filename(filename: str | None) -> str:
    value = (filename or "upload").replace("\r", "").replace("\n", "")
    value = Path(value).name[:255]
    return value or "upload"


def sanitize_content_type(filename: str, _claimed_type: str | None = None) -> str:
    """Infer a passive media type from a safe extension; never trust multipart MIME."""
    suffix = Path(_safe_original_filename(filename)).suffix.lower()
    return SAFE_MIME_BY_EXTENSION.get(suffix, "application/octet-stream")


def resolve_object_path(root: Path, tenant_id: UUID, object_key: str) -> Path:
    if not isinstance(tenant_id, UUID) or not isinstance(object_key, str):
        raise ValueError("invalid object key")
    if "\\" in object_key:
        raise ValueError("invalid object key")
    key = PurePosixPath(object_key)
    parts = key.parts
    if key.is_absolute() or ".." in parts or len(parts) != 3 or parts[0] != str(tenant_id):
        raise ValueError("file path escapes tenant root")
    _validated_category(parts[1])
    resolved_root = Path(root).resolve()
    tenant_root = (resolved_root / str(tenant_id)).resolve()
    candidate = (resolved_root / Path(*parts)).resolve()
    if candidate == tenant_root or tenant_root not in candidate.parents:
        raise ValueError("file path escapes tenant root")
    return candidate


def save_upload_file(
    upload_file: UploadFile,
    tenant_id: UUID,
    category: str,
    root: Path = UPLOAD_ROOT,
    *,
    resource_type: str | None = None,
    resource_id: UUID | None = None,
    max_size: int = MAX_UPLOAD_SIZE,
) -> StoredFile:
    category = _validated_category(category)
    original_filename = _safe_original_filename(upload_file.filename)
    suffix = Path(original_filename).suffix
    extension = suffix.lower() if SAFE_EXTENSION.fullmatch(suffix) else ""
    object_key = f"{tenant_id}/{category}/{uuid4()}{extension}"
    final_path = resolve_object_path(Path(root), tenant_id, object_key)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = final_path.with_name(final_path.name + ".part")
    size = 0
    try:
        with partial_path.open("xb") as target:
            while chunk := upload_file.file.read(1024 * 1024):
                size += len(chunk)
                if size > max_size:
                    raise ValueError("uploaded file is too large")
                target.write(chunk)
        if size == 0:
            raise ValueError("uploaded file is empty")
        partial_path.replace(final_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise
    return StoredFile(
        id=uuid4(),
        tenant_id=tenant_id,
        object_key=object_key,
        original_filename=original_filename,
        content_type=sanitize_content_type(original_filename, upload_file.content_type),
        size=size,
        category=category,
        resource_type=resource_type,
        resource_id=resource_id,
    )


def stored_file_path(record: StoredFile, root: Path = UPLOAD_ROOT) -> Path:
    return resolve_object_path(Path(root), record.tenant_id, record.object_key)


def delete_object_file(root: Path, tenant_id: UUID, object_key: str) -> None:
    path = resolve_object_path(Path(root), tenant_id, object_key)
    if path.exists() and not path.is_file():
        raise ValueError("stored object is not a regular file")
    path.unlink(missing_ok=True)


@dataclass(frozen=True)
class StoredFileLocation:
    tenant_id: UUID
    object_key: str
    file_id: UUID


def tenant_resource_files(
    db, tenant_id: UUID, resource_type: str, resource_id: UUID, category: str
):
    _validated_category(category)
    return db.query(StoredFile).filter(
        StoredFile.tenant_id == tenant_id,
        StoredFile.resource_type == resource_type,
        StoredFile.resource_id == resource_id,
        StoredFile.category == category,
    ).all()


def tenant_files_from_urls(
    db, tenant_id: UUID, resource_type: str, resource_id: UUID, category: str, urls
):
    _validated_category(category)
    file_ids = []
    for value in urls:
        if not isinstance(value, str):
            continue
        match = FILE_DOWNLOAD_URL.fullmatch(value)
        if match is None:
            continue
        try:
            file_ids.append(UUID(match.group(1)))
        except ValueError:
            continue
    if not file_ids:
        return []
    return db.query(StoredFile).filter(
        StoredFile.id.in_(file_ids),
        StoredFile.tenant_id == tenant_id,
        StoredFile.resource_type == resource_type,
        StoredFile.resource_id == resource_id,
        StoredFile.category == category,
    ).all()


def stage_file_deletions(db, records) -> list[StoredFileLocation]:
    locations = []
    seen = set()
    for record in records:
        if record.id in seen:
            continue
        seen.add(record.id)
        locations.append(StoredFileLocation(record.tenant_id, record.object_key, record.id))
        db.delete(record)
    return locations


def unlink_file_locations(locations, root: Path = UPLOAD_ROOT) -> None:
    for location in locations:
        try:
            delete_object_file(root, location.tenant_id, location.object_key)
        except Exception:
            logger.warning(
                "Stored file cleanup failed",
                extra={"tenant_id": str(location.tenant_id), "file_id": str(location.file_id)},
            )


def cleanup_new_file(db, record: StoredFile, root: Path = UPLOAD_ROOT) -> None:
    db.rollback()
    try:
        delete_object_file(root, record.tenant_id, record.object_key)
    except Exception:
        logger.warning(
            "New stored file cleanup failed",
            extra={"tenant_id": str(record.tenant_id), "file_id": str(record.id)},
        )


def commit_file_replacement(
    db, new_file: StoredFile, old_files, root: Path = UPLOAD_ROOT
) -> None:
    locations = stage_file_deletions(db, old_files)
    try:
        db.commit()
    except Exception:
        cleanup_new_file(db, new_file, root=root)
        raise
    unlink_file_locations(locations, root=root)
