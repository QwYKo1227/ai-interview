from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config.database import get_unscoped_db
from app.core.tenant_dependencies import get_current_user_dep, get_tenant_db
from app.models.file_models import StoredFile
from app.models.models import User
from app.services.public_token_service import enforce_public_request_tenant, resolve_public_token
from app.utils.file_storage import UPLOAD_ROOT as DEFAULT_UPLOAD_ROOT, resolve_object_path


UPLOAD_ROOT = DEFAULT_UPLOAD_ROOT
router = APIRouter(prefix="/files", tags=["files"])
public_router = APIRouter(prefix="/public/files", tags=["public-files"])


def _not_found():
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")


def _response(record: StoredFile) -> FileResponse:
    try:
        path = resolve_object_path(Path(UPLOAD_ROOT), record.tenant_id, record.object_key)
    except ValueError as exc:
        raise _not_found() from exc
    if not path.is_file():
        raise _not_found()
    safe_name = record.original_filename.replace("\r", "").replace("\n", "")
    disposition = f"attachment; filename*=UTF-8''{quote(safe_name, safe='')}"
    return FileResponse(
        path,
        media_type=record.content_type or "application/octet-stream",
        headers={"Content-Disposition": disposition, "X-Content-Type-Options": "nosniff"},
    )


@router.get("/{file_id}")
def download_file(
    file_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user_dep),
):
    record = db.query(StoredFile).filter(
        StoredFile.id == file_id, StoredFile.tenant_id == current_user.tenant_id
    ).first()
    if record is None:
        raise _not_found()
    return _response(record)


@public_router.get("/{token}")
def download_public_file(
    token: str,
    request: Request,
    tenant_code: str | None = None,
    db: Session = Depends(get_unscoped_db),
):
    resolved = resolve_public_token(db, token, "stored_file")
    enforce_public_request_tenant(
        db, request_host=request.headers.get("host", ""),
        tenant_id=resolved.tenant_id, tenant_code=tenant_code,
    )
    return _response(resolved.resource)
