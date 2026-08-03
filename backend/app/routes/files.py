from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config.database import get_unscoped_db
from app.core.tenant_dependencies import get_current_user_dep, get_tenant_db
from app.models.file_models import StoredFile
from app.models.models import (
    DepartmentReview,
    Interview,
    QuestionBank,
    Resume,
    User,
    UserRole,
)
from app.schemas.file import PublicFileTokenRequest, PublicFileTokenResponse
from app.services.public_token_service import enforce_public_request_tenant, issue_public_token, resolve_public_token
from app.utils.file_storage import UPLOAD_ROOT as DEFAULT_UPLOAD_ROOT, resolve_object_path, sanitize_content_type
from app.core.proxy import resolve_request_host
from app.services.interview_access import can_access_interview


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
        media_type=sanitize_content_type(record.original_filename, record.content_type),
        headers={"Content-Disposition": disposition, "X-Content-Type-Options": "nosniff"},
    )


def _can_access_file(
    db: Session,
    current_user: User,
    record: StoredFile,
    *,
    allow_assigned_resume: bool = False,
) -> bool:
    """Authorize the linked business resource, not merely a guessable file UUID."""

    if record.resource_id is None or record.resource_type is None:
        return False
    role = getattr(current_user.role, "value", current_user.role)
    resource_exists = False
    if record.resource_type == "resume":
        resource_exists = (
            db.query(Resume.id)
            .filter(Resume.id == record.resource_id, Resume.file_id == record.id)
            .first()
            is not None
        )
    elif record.resource_type == "question_bank":
        resource_exists = (
            db.query(QuestionBank.id)
            .filter(
                QuestionBank.id == record.resource_id,
                QuestionBank.source_file_id == record.id,
            )
            .first()
            is not None
        )
    elif record.resource_type == "interview":
        interview = (
            db.query(Interview)
            .filter(Interview.id == record.resource_id)
            .first()
        )
        return interview is not None and can_access_interview(db, interview, current_user)
    if not resource_exists:
        return False
    if role in {UserRole.ADMIN.value, UserRole.HR.value}:
        return True
    if record.resource_type != "resume" or not allow_assigned_resume:
        return False
    active_department_review = (
        db.query(DepartmentReview.id)
        .filter(
            DepartmentReview.tenant_id == current_user.tenant_id,
            DepartmentReview.resume_id == record.resource_id,
            DepartmentReview.reviewer_id == current_user.id,
            DepartmentReview.is_completed.is_(False),
        )
        .first()
    )
    if active_department_review is not None:
        return True
    interviews = (
        db.query(Interview)
        .filter(Interview.resume_id == record.resource_id)
        .all()
    )
    return any(can_access_interview(db, interview, current_user) for interview in interviews)


@router.get("/{file_id}")
def download_file(
    file_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user_dep),
):
    record = db.query(StoredFile).filter(
        StoredFile.id == file_id, StoredFile.tenant_id == current_user.tenant_id
    ).first()
    if record is None or not _can_access_file(
        db, current_user, record, allow_assigned_resume=True
    ):
        raise _not_found()
    return _response(record)


@router.post("/{file_id}/public-token", response_model=PublicFileTokenResponse)
def create_public_file_token(
    file_id: UUID,
    payload: PublicFileTokenRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user_dep),
):
    record = db.query(StoredFile).filter(
        StoredFile.id == file_id, StoredFile.tenant_id == current_user.tenant_id
    ).first()
    if record is None or not _can_access_file(db, current_user, record):
        raise _not_found()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=payload.ttl_seconds)
    raw_token = issue_public_token(db, current_user.tenant_id, "stored_file", record.id, expires_at)
    return PublicFileTokenResponse(
        token=raw_token,
        url=f"/api/public/files/{raw_token}",
        expires_at=expires_at,
    )


@public_router.get("/{token}")
def download_public_file(
    token: str,
    request: Request,
    tenant_code: str | None = None,
    db: Session = Depends(get_unscoped_db),
):
    resolved = resolve_public_token(db, token, "stored_file")
    enforce_public_request_tenant(
        db, request_host=resolve_request_host(request),
        tenant_id=resolved.tenant_id, tenant_code=tenant_code,
    )
    return _response(resolved.resource)
