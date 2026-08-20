from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks, Request
from sqlalchemy.orm import Session
from app.config.database import get_unscoped_db
from app.core.tenant_dependencies import get_tenant_db
from app.schemas.resume import (
    ResumeResponse, ResumeCreate, ResumeUpdate,
    DepartmentReviewCreate, DepartmentReviewUpdate, DepartmentReviewResponse,
    AssignedDepartmentReviewResponse, DepartmentReviewLinkResponse,
    DepartmentReviewEmailPreviewRequest, DepartmentReviewEmailPreviewResponse,
    DepartmentReviewEmailSendRequest,
    HRDecisionCreate, HRDecisionResponse,
    DuplicateCheckRequest, DuplicateCheckResponse, DuplicateResumeSummary,
    DepartmentReviewSummary
)
from app.services.resume_service import (
    upload_resume, upload_public_resume, get_resumes, get_resume, update_resume, delete_resume,
    batch_upload_resumes, reparse_resume,
    check_duplicate_resume, create_department_review, get_department_reviews,
    get_assigned_department_reviews,
    complete_department_review, reassign_department_reviewer,
    reissue_department_review_link, aggregate_department_reviews, submit_hr_decision,
    confirm_rejection, override_rejection, get_duplicate_resumes,
    get_resume_with_reviews, transfer_resume_position
)
from app.models.models import (
    DepartmentReview, Position, ResumeStatus, RejectReasonCategory, User, UserRole, Resume,
)
from app.core.security import check_roles
from app.routes.auth import get_current_user
from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime
from app.services.public_token_service import resolve_public_tenant, resolve_public_token
from app.core.rate_limit import enforce_rate_limit
from app.core.proxy import resolve_request_host
from app.services.recruitment_access import (
    can_access_resume,
    is_admin,
    require_position_access,
    require_resume_access,
)
import hashlib
import re

router = APIRouter(
    prefix="/resumes",
    tags=["resumes"]
)

# ==================== 简历列表 ====================

@router.get("", response_model=List[ResumeResponse])
def get_resumes_route(
    skip: int = 0,
    limit: int = 100,
    candidate_name: str = None,
    status: str = None,
    position_id: Optional[UUID] = None,
    reviewer_id: Optional[UUID] = None,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    return get_resumes(
        db,
        skip=skip,
        limit=limit,
        candidate_name=candidate_name,
        status=status,
        position_id=position_id,
        reviewer_id=reviewer_id,
        current_user=current_user,
    )

# ==================== 简历查重 ====================

@router.post("/check-duplicate", response_model=DuplicateCheckResponse)
def check_duplicate_route(
    request: DuplicateCheckRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """
    检查简历是否重复（基于邮箱/手机号）
    """
    require_position_access(db, request.position_id, current_user)
    existing = check_duplicate_resume(db, request.email, request.contact, request.position_id)

    if existing:
        return DuplicateCheckResponse(
            is_duplicate=True,
            existing_resume=ResumeResponse.model_validate(existing),
            message=f"发现重复简历：{existing.candidate_name or '未知候选人'}"
        )

    return DuplicateCheckResponse(
        is_duplicate=False,
        existing_resume=None,
        message="未发现重复简历"
    )

# ==================== 简历上传 ====================

def validate_pdf_file(file: UploadFile):
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="只允许上传 PDF 格式的文件")
    if file.content_type and file.content_type != 'application/pdf':
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="只允许上传 PDF 格式的文件")
    return file


def _public_upload_rate_subject(
    tenant_id: UUID,
    position_id: UUID,
    *,
    candidate_name: str | None,
    email: str | None,
    contact: str | None,
) -> str | None:
    """Build one stable, non-reversible candidate identity for rate limiting."""

    normalized_name = " ".join((candidate_name or "").strip().casefold().split())
    normalized_email = (email or "").strip().casefold()
    normalized_contact = re.sub(r"\D+", "", contact or "")
    if not any((normalized_name, normalized_email, normalized_contact)):
        return None
    payload = "\x1f".join(
        (
            str(tenant_id),
            str(position_id),
            normalized_name,
            normalized_email,
            normalized_contact,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

# 注意：单简历上传保持公开，因为应聘者可能通过公开链接投递
@router.post("", response_model=ResumeResponse)
def create_resume_route(
    background_tasks: BackgroundTasks,
    request: Request,
    position_id: UUID = Form(...),
    tenant_code: str = Form(None),
    file: UploadFile = File(...),
    candidate_name: str = Form(None),  # 公开链接上传时由应聘者填写
    email: str = Form(None),
    contact: str = Form(None),
    db: Session = Depends(get_unscoped_db)
):
    validate_pdf_file(file)
    tenant_id = resolve_public_tenant(
        db, request_host=resolve_request_host(request), tenant_code=tenant_code
    )
    enforce_rate_limit(request, "public_upload_tenant", tenant_id)
    candidate_subject = _public_upload_rate_subject(
        tenant_id,
        position_id,
        candidate_name=candidate_name,
        email=email,
        contact=contact,
    )
    if candidate_subject is None:
        enforce_rate_limit(request, "public_upload")
    else:
        enforce_rate_limit(request, "public_upload", candidate_subject)
    return upload_public_resume(
        db, file, position_id, background_tasks, candidate_name, email, contact
    )

@router.post("/batch", response_model=List[ResumeResponse])
def batch_upload_resumes_route(
    background_tasks: BackgroundTasks,
    position_id: UUID = Form(...),
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    require_position_access(db, position_id, current_user)
    for f in files:
        validate_pdf_file(f)
    return batch_upload_resumes(db, files, position_id, background_tasks)


@router.get(
    "/my-reviews",
    response_model=List[AssignedDepartmentReviewResponse],
)
def get_my_reviews_route(
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    return get_assigned_department_reviews(db, current_user.id)


# ==================== 简历详情与更新 ====================

@router.get("/{resume_id}/duplicates", response_model=List[DuplicateResumeSummary])
def get_duplicate_resumes_route(
    resume_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user),
):
    require_resume_access(db, resume_id, current_user)
    duplicates = get_duplicate_resumes(db, resume_id)
    if duplicates is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    return [item for item in duplicates if can_access_resume(db, item, current_user)]


@router.get("/{resume_id}", response_model=ResumeResponse)
def get_resume_route(
    resume_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    require_resume_access(db, resume_id, current_user)
    resume = get_resume_with_reviews(db, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume

@router.put("/{resume_id}", response_model=ResumeResponse)
def update_resume_route(
    resume_id: UUID,
    resume: ResumeUpdate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    require_resume_access(db, resume_id, current_user, manage=True)
    db_resume = update_resume(db, resume_id, resume)
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return db_resume

@router.delete("/{resume_id}", response_model=ResumeResponse)
def delete_resume_route(
    resume_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    require_resume_access(db, resume_id, current_user, manage=True)
    db_resume = delete_resume(db, resume_id)
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return db_resume

@router.post("/{resume_id}/reparse", response_model=ResumeResponse)
def reparse_resume_route(
    resume_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    require_resume_access(db, resume_id, current_user, manage=True)
    resume = reparse_resume(db, resume_id, background_tasks)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume

# ==================== 部门评审 ====================

@router.get("/{resume_id}/department-reviews", response_model=DepartmentReviewSummary)
def get_department_reviews_route(
    resume_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    require_resume_access(db, resume_id, current_user)
    """
    获取部门评审汇总报告
    """
    return aggregate_department_reviews(db, resume_id)


@router.post("/{resume_id}/department-reviews", response_model=DepartmentReviewResponse)
def create_department_review_route(
    resume_id: UUID,
    reviewer_id: UUID = Form(...),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    require_resume_access(db, resume_id, current_user, manage=True)
    """
    指派部门评审人
    """
    return create_department_review(db, resume_id, reviewer_id)


def _require_department_review(
    db: Session,
    resume_id: UUID,
    review_id: UUID,
) -> DepartmentReview:
    review = db.query(DepartmentReview).filter(
        DepartmentReview.id == review_id,
        DepartmentReview.resume_id == resume_id,
    ).first()
    if review is None:
        raise HTTPException(status_code=404, detail="评审记录不存在")
    return review


@router.post(
    "/{resume_id}/department-reviews/{review_id}/email-preview",
    response_model=DepartmentReviewEmailPreviewResponse,
)
def preview_department_review_email(
    resume_id: UUID,
    review_id: UUID,
    payload: DepartmentReviewEmailPreviewRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    """预览发送给部门评审人的指派邮件。"""
    resume = require_resume_access(db, resume_id, current_user, manage=True)
    review = _require_department_review(db, resume_id, review_id)
    resolved = resolve_public_token(db, payload.public_token, "department_review")
    if resolved.resource_id != review.id:
        raise HTTPException(status_code=404, detail="Public resource not found")

    reviewer = db.query(User).filter(User.id == review.reviewer_id).first()
    if reviewer is None or not reviewer.email:
        raise HTTPException(status_code=400, detail="评审人邮箱为空")

    from app.services.mail_service import get_mail_service
    position_title = resume.position.title if resume.position else "未知岗位"
    content = get_mail_service(db)._render_template("review_notification.html", {
        "reviewer_name": reviewer.full_name or reviewer.email,
        "candidate_name": resume.candidate_name or "候选人",
        "position_title": position_title,
        "match_score": resume.match_score or 0,
        "submitted_at": resume.created_at.strftime("%Y-%m-%d %H:%M") if resume.created_at else "",
        "hr_review": resume.hr_review,
        "review_url": str(payload.review_url),
        "current_year": datetime.utcnow().year,
    })
    return {
        "review_id": review.id,
        "to_email": reviewer.email,
        "reviewer_name": reviewer.full_name or reviewer.email,
        "candidate_name": resume.candidate_name,
        "subject": f"简历评审邀请 - {position_title}",
        "content": content,
    }


@router.post("/{resume_id}/department-reviews/{review_id}/send-email")
def send_department_review_email(
    resume_id: UUID,
    review_id: UUID,
    payload: DepartmentReviewEmailSendRequest,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    """发送可编辑的部门评审指派邮件。"""
    require_resume_access(db, resume_id, current_user, manage=True)
    review = _require_department_review(db, resume_id, review_id)
    reviewer = db.query(User).filter(User.id == review.reviewer_id).first()
    if reviewer is None or not reviewer.email:
        raise HTTPException(status_code=400, detail="评审人邮箱为空")

    from app.services.mail_service import get_mail_service

    if not get_mail_service(db)._send_email(
        to_email=reviewer.email,
        subject=payload.subject,
        html_content=payload.content,
    ):
        raise HTTPException(status_code=500, detail="邮件发送失败")
    return {"message": "邮件发送成功"}


@router.put("/{resume_id}/department-reviews/{review_id}", response_model=DepartmentReviewResponse)
def complete_department_review_route(
    resume_id: UUID,
    review_id: UUID,
    technical_score: int = Form(None),
    experience_score: int = Form(None),
    overall_score: int = Form(None),
    recommendation: str = Form(None),
    comment: str = Form(None),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(get_current_user)
):
    """
    完成部门评审
    """
    review_data = DepartmentReviewUpdate(
        technical_score=technical_score,
        experience_score=experience_score,
        overall_score=overall_score,
        recommendation=recommendation,
        comment=comment
    )
    return complete_department_review(
        db,
        resume_id,
        review_id,
        current_user.id,
        review_data,
    )


@router.put(
    "/{resume_id}/department-reviews/{review_id}/reviewer",
    response_model=DepartmentReviewResponse,
)
def reassign_department_reviewer_route(
    resume_id: UUID,
    review_id: UUID,
    reviewer_id: UUID = Form(...),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    require_resume_access(db, resume_id, current_user, manage=True)
    return reassign_department_reviewer(db, resume_id, review_id, reviewer_id)


@router.post(
    "/{resume_id}/department-reviews/{review_id}/review-link",
    response_model=DepartmentReviewLinkResponse,
)
def reissue_department_review_link_route(
    resume_id: UUID,
    review_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR])),
):
    require_resume_access(db, resume_id, current_user, manage=True)
    return {
        "public_token": reissue_department_review_link(db, resume_id, review_id),
    }


# ==================== HR决策 ====================

@router.post("/{resume_id}/hr-decision", response_model=ResumeResponse)
def submit_hr_decision_route(
    resume_id: UUID,
    decision_data: HRDecisionCreate,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    """
    HR提交最终决策
    """
    # decision_data.hr_id is retained for request compatibility but is not trusted.
    require_resume_access(db, resume_id, current_user, manage=True)
    return submit_hr_decision(db, resume_id, current_user.id, decision_data)


@router.post("/{resume_id}/confirm-rejection", response_model=ResumeResponse)
def confirm_rejection_route(
    resume_id: UUID,
    reason_category: str = Form(...),
    reason_detail: str = Form(None),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    """
    确认淘汰低分简历
    """
    require_resume_access(db, resume_id, current_user, manage=True)
    try:
        reason_category_enum = RejectReasonCategory(reason_category)
    except ValueError:
        valid_values = [e.value for e in RejectReasonCategory]
        raise HTTPException(status_code=400, detail=f"无效的淘汰原因，有效值为: {valid_values}")
    
    hr_id = current_user.id
    return confirm_rejection(db, resume_id, hr_id, reason_category_enum, reason_detail)


@router.post("/{resume_id}/override-rejection", response_model=ResumeResponse)
def override_rejection_route(
    resume_id: UUID,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    """
    覆盖AI淘汰建议，恢复到评审流程
    """
    require_resume_access(db, resume_id, current_user, manage=True)
    hr_id = current_user.id
    return override_rejection(db, resume_id, hr_id)


@router.post("/{resume_id}/transfer", response_model=ResumeResponse)
def transfer_resume_position_route(
    resume_id: UUID,
    background_tasks: BackgroundTasks,
    new_position_id: UUID = Form(...),
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    """
    将简历转岗到其他岗位，并重新解析
    """
    return transfer_resume_position(
        db,
        resume_id,
        new_position_id,
        background_tasks,
        current_user=current_user,
    )


@router.get("/queue/status")
def get_queue_status(
    current_user: User = Depends(check_roles([UserRole.ADMIN]))
):
    from app.services.task_queue import get_task_queue
    queue = get_task_queue()
    return queue.get_stats(current_user.tenant_id)


@router.get("/queue/task/{task_id}")
def get_task_status(
    task_id: str,
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    from app.services.task_queue import get_task_queue
    queue = get_task_queue()
    status = queue.get_status(task_id, current_user.tenant_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")
    resource_id = queue.get_resource_id(task_id, current_user.tenant_id)
    if resource_id is None:
        raise HTTPException(status_code=404, detail="Task not found")
    require_resume_access(db, resource_id, current_user, manage=True)
    return status


@router.post("/fix-stuck")
def fix_stuck_resumes(
    db: Session = Depends(get_tenant_db),
    current_user: User = Depends(check_roles([UserRole.ADMIN, UserRole.HR]))
):
    from datetime import datetime, timedelta
    from app.services.task_queue import get_task_queue

    queue = get_task_queue()
    queue_stats = queue.get_stats(current_user.tenant_id) if is_admin(current_user) else None

    stuck_query = db.query(Resume).join(Position, Resume.position_id == Position.id).filter(
        Resume.parse_status == "processing",
        Resume.updated_at < datetime.utcnow() - timedelta(minutes=10)
    )
    if not is_admin(current_user):
        stuck_query = stuck_query.filter(Position.hiring_manager_id == current_user.id)
    stuck_resumes = stuck_query.all()

    fixed_count = 0
    for resume in stuck_resumes:
        task_status = queue.get_status(str(resume.id), current_user.tenant_id)

        if task_status is None or task_status["status"] in ["completed", "failed"]:
            resume.parse_status = "failed"
            resume.parse_error = "解析超时，请重新解析"
            resume.candidate_name = "解析失败"
            fixed_count += 1

    db.commit()

    return {
        "fixed_count": fixed_count,
        "queue_stats": queue_stats
    }
