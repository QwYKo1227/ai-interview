from uuid import UUID
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session, joinedload
from app.models.models import Interview, Resume, Position, InterviewStatus, InterviewResult, QuestionBank, ResumeStatus, ScreeningResult, InterviewPanel, User, UserRole
from app.schemas.interview import InterviewCreate, InterviewUpdate, InterviewScore, InterviewScheduleUpdate
from fastapi import BackgroundTasks
import logging
from app.core.observability import background_task_context
from app.config.tenant_session import tenant_session
from app.models.file_models import StoredFile
from app.utils.file_storage import stored_file_path
from app.utils.file_storage import UPLOAD_ROOT, stage_file_deletions, tenant_resource_files, unlink_file_locations
from app.services.interview_access import can_score_interview, is_interviewer_assigned
from app.services.interview_timing import require_interview_start_time
from app.services.resume_interview_status import (
    apply_final_decision,
    mark_legacy_interview_completed,
    mark_legacy_interview_ended,
    mark_interview_scheduled,
    mark_interview_started,
    restore_after_cancellation,
)

logger = logging.getLogger(__name__)

# 中国时区 UTC+8
CHINA_TIMEZONE = timezone(timedelta(hours=8))

def format_datetime_cn(dt: datetime) -> str:
    """将UTC时间转换为中国时区并格式化"""
    if not dt:
        return 'N/A'
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_cn = dt.astimezone(CHINA_TIMEZONE)
    return dt_cn.strftime('%Y-%m-%d %H:%M')

def start_interview(db: Session, interview_id: UUID):
    """
    开始面试，将状态从 SCHEDULED 改为 IN_PROGRESS，并记录开始时间。
    """
    db_interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not db_interview:
        return None

    if db_interview.status != InterviewStatus.SCHEDULED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start interview with status {db_interview.status.value}"
        )

    require_interview_start_time(db_interview)

    db_interview.status = InterviewStatus.IN_PROGRESS
    db_interview.lifecycle_state = "in_progress"
    db_interview.started_at = datetime.utcnow()
    mark_interview_started(db_interview)
    db.commit()
    db.refresh(db_interview)

    print(f"Interview {interview_id} status changed to IN_PROGRESS, started_at: {db_interview.started_at}")
    return db_interview

def submit_interview_panel_score(
    db: Session,
    interview_id: UUID,
    interviewer_id: UUID,
    score_data: InterviewScore,
    *,
    actor: User | None = None,
):
    """
    Submit score for a specific interviewer (panel member).
    统一的评分提交入口，单面试官和多面试官都使用此函数。
    """
    db_interview = db.query(Interview).get(interview_id)
    if not db_interview:
        return None, False

    authorized = (
        can_score_interview(db, db_interview, actor)
        if actor is not None and actor.id == interviewer_id
        else is_interviewer_assigned(db, db_interview, interviewer_id)
    )
    if not authorized:
        raise HTTPException(status_code=403, detail="Interview assignment required")

    if db_interview.status == InterviewStatus.SCHEDULED:
        db_interview.status = InterviewStatus.IN_PROGRESS
        db_interview.lifecycle_state = "in_progress"
        mark_interview_started(db_interview)
        print(f"Interview {interview_id} status auto-changed to IN_PROGRESS on first score submission")
        db.commit()

    panel = db.query(InterviewPanel).filter(
        InterviewPanel.interview_id == interview_id,
        InterviewPanel.interviewer_id == interviewer_id
    ).first()

    avg_score = sum(score_data.scores.values()) // len(score_data.scores) if score_data.scores else 0

    if not panel:
        panel = InterviewPanel(
            tenant_id=db_interview.tenant_id,
            interview_id=interview_id,
            interviewer_id=interviewer_id,
            scores=score_data.scores,
            comments=score_data.comments,
            total_score=avg_score,
            is_submitted=True
        )
        db.add(panel)
    else:
        panel.scores = score_data.scores
        panel.comments = score_data.comments
        panel.total_score = avg_score
        panel.is_submitted = True

    db.commit()
    db.refresh(panel)
    
    db_interview = db.query(Interview).get(interview_id)
    all_submitted = False
    if db_interview and db_interview.panel_members:
        submitted_panels = db.query(InterviewPanel).filter(
            InterviewPanel.interview_id == interview_id,
            InterviewPanel.is_submitted == True
        ).all()
        
        submitted_interviewer_ids = [str(p.interviewer_id) for p in submitted_panels]
        required_interviewer_ids = [str(uid) for uid in db_interview.panel_members]
        
        print(f"[Panel Score] Submitted IDs: {submitted_interviewer_ids}")
        print(f"[Panel Score] Required IDs: {required_interviewer_ids}")
        
        all_submitted = all(uid in submitted_interviewer_ids for uid in required_interviewer_ids)
        print(f"[Panel Score] All submitted: {all_submitted}")

    return panel, all_submitted

def get_interview_panels(db: Session, interview_id: UUID):
    return db.query(InterviewPanel).filter(InterviewPanel.interview_id == interview_id).all()

def aggregate_panel_scores(db: Session, interview_id: UUID, background_tasks: BackgroundTasks):
    """
    Aggregate scores from all panels to main interview record and generate AI evaluation.
    """
    panels = db.query(InterviewPanel).filter(
        InterviewPanel.interview_id == interview_id,
        InterviewPanel.is_submitted == True
    ).all()
    
    if not panels:
        return None
        
    # Aggregate logic: Average scores per question
    aggregated_scores = {}
    aggregated_comments = {}
    
    # Assuming all panels use the same question indices
    # We need to collect all scores for each question index
    question_scores_map = {} # { "0": [8, 9], "1": [7, 8] }
    
    # Collect aggregated transcripts
    aggregated_transcripts = {}
    
    for panel in panels:
        if not panel.scores: continue
        for q_idx, score in panel.scores.items():
            if q_idx not in question_scores_map:
                question_scores_map[q_idx] = []
            question_scores_map[q_idx].append(score)
            
        # Collect comments
        if panel.comments:
            for q_idx, comment in panel.comments.items():
                interviewer = db.query(User).get(panel.interviewer_id)
                name = interviewer.full_name if interviewer else "Interviewer"
                if q_idx not in aggregated_comments:
                    aggregated_comments[q_idx] = ""
                aggregated_comments[q_idx] += f"**{name}**: {comment}\n\n"
        
        # Collect transcripts (just concatenate or use first valid one)
        # Ideally, we should group them by question. 
        # If multiple recordings exist for same question (e.g. from different interviewers? unlikely for same candidate unless split),
        # we can append them.
        if panel.transcripts:
            for q_idx, transcript in panel.transcripts.items():
                if q_idx not in aggregated_transcripts:
                    aggregated_transcripts[q_idx] = ""
                # Avoid duplicate transcript if multiple panels upload same? 
                # Usually only one interviewer records, or they record sequentially.
                # Let's append with interviewer name if needed, or just append.
                if transcript:
                    interviewer = db.query(User).get(panel.interviewer_id)
                    name = interviewer.full_name if interviewer else "Interviewer"
                    aggregated_transcripts[q_idx] += f"[{name}记录]: {transcript}\n"

    # Calculate averages
    for q_idx, scores_list in question_scores_map.items():
        if scores_list:
            aggregated_scores[q_idx] = round(sum(scores_list) / len(scores_list))
            
    # Update main interview record
    db_interview = db.query(Interview).get(interview_id)
    if db_interview:
        db_interview.scores = aggregated_scores
        db_interview.comments = aggregated_comments
        db_interview.transcripts = aggregated_transcripts
        
        # Trigger AI evaluation with detailed panel comments AND transcripts
        # Convert aggregated_comments to a string format for AI
        panel_details_str = ""
        for q_idx, comment_str in aggregated_comments.items():
            panel_details_str += f"Question {q_idx} Comments:\n{comment_str}\n"
            
        # Add transcripts to context
        transcript_context = ""
        for q_idx, trans in aggregated_transcripts.items():
             transcript_context += f"Question {q_idx} Candidate Answer:\n{trans}\n"

        background_tasks.add_task(
            generate_evaluation_background,
            db_interview.tenant_id,
            db_interview.id,
            {
                "scores": aggregated_scores,
                "panel_details": panel_details_str,
                "transcripts": transcript_context
            }
        )

        db_interview.status = InterviewStatus.ANALYZING
        mark_legacy_interview_ended(db_interview)
        db.commit()
        db.refresh(db_interview)
        print(f"Panel scores aggregated for interview {interview_id}, status changed to ANALYZING")
        return db_interview
    return None
from fastapi import HTTPException
from app.services.ai_service import generate_interview_questions, generate_interview_evaluation
from app.services.resume_service import read_file_content
import json
from datetime import timezone

from fastapi import BackgroundTasks

def _normalize_dt_utc(dt):
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

@background_task_context
def generate_questions_background(tenant_id: UUID, interview_id: UUID, question_bank_ids: list, question_count: int, interview_category: str = 'technical'):
    with tenant_session(tenant_id) as db:
        return _generate_questions_background(
            db, interview_id, question_bank_ids, question_count, interview_category
        )


def _generate_questions_background(db: Session, interview_id: UUID, question_bank_ids: list, question_count: int, interview_category: str = 'technical'):
    try:
        interview = db.query(Interview).filter(Interview.id == interview_id).first()
        if not interview:
            logger.warning(
                "Interview question resource not found",
                extra={"resource_id": str(interview_id)},
            )
            return

        resume = db.query(Resume).filter(Resume.id == interview.resume_id).first()
        position = db.query(Position).filter(Position.id == interview.position_id).first()

        if not resume or not position:
            return

        # 获取参考题库内容
        qb_content = ""
        if question_bank_ids:
            qbs = db.query(QuestionBank).filter(QuestionBank.id.in_(question_bank_ids)).all()
            for qb in qbs:
                if qb.source_file:
                    source_path = qb.source_file
                    if qb.source_file_id:
                        stored = db.query(StoredFile).filter(StoredFile.id == qb.source_file_id).first()
                        if stored:
                            source_path = str(stored_file_path(stored))
                    content = read_file_content(source_path)
                    if content:
                        qb_content += f"\n--- 参考题库: {qb.name} ---\n{content[:5000]}\n"

        # 生成面试题
        position_desc = f"{position.title}\n{position.description}\n{position.requirements}"
        resume_data = resume.parsed_data if resume.parsed_data else {}

        questions = generate_interview_questions(
            resume_data,
            position_desc,
            qb_content,
            question_count,
            interview_category,
            db=db,
        )

        interview.questions = questions
        db.commit()
        
    except Exception:
        db.rollback()
        logger.error(
            "Interview question generation failed",
            extra={"resource_id": str(interview_id)},
        )
        raise RuntimeError("interview background task failed") from None

def create_interview(db: Session, interview: InterviewCreate, background_tasks: BackgroundTasks):
    # 检查简历和岗位是否存在
    resume = db.query(Resume).filter(Resume.id == interview.resume_id).first()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    position = db.query(Position).filter(Position.id == interview.position_id).first()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    panel_member_ids = []
    seen_panel_members = set()
    for interviewer_id in interview.panel_members or []:
        try:
            interviewer_uuid = UUID(interviewer_id) if isinstance(interviewer_id, str) else interviewer_id
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid panel member ID")
        if interviewer_uuid in seen_panel_members:
            raise HTTPException(status_code=400, detail="Duplicate panel member ID")
        if not db.query(User).filter(User.id == interviewer_uuid).first():
            raise HTTPException(status_code=404, detail="Panel member not found")
        seen_panel_members.add(interviewer_uuid)
        panel_member_ids.append(interviewer_uuid)

    for question_bank_id in interview.question_bank_ids or []:
        if not db.query(QuestionBank).filter(QuestionBank.id == question_bank_id).first():
            raise HTTPException(status_code=404, detail="Question bank not found")

    interview_category = interview.interview_category or 'technical'

    db_interview = Interview(
        tenant_id=resume.tenant_id,
        resume_id=interview.resume_id,
        position_id=interview.position_id,
        interviewer=interview.interviewer,
        interview_time=_normalize_dt_utc(interview.interview_time),
        questions=None if not interview.skip_ai_questions else [], # None means generating, [] means skipped
        status=InterviewStatus.SCHEDULED,
        panel_members=[str(member_id) for member_id in panel_member_ids],
        round=interview.round or 1,
        # 正确保存面试类型和地点字段
        interview_type=interview.interview_type or "onsite",
        interview_category=interview_category,
        interview_location=interview.interview_location,
        meeting_link=interview.meeting_link
    )

    db.add(db_interview)
    db.flush()
    mark_interview_scheduled(db_interview)
    db.commit()
    db.refresh(db_interview)

    if panel_member_ids:
        for interviewer_uuid in panel_member_ids:
            panel = InterviewPanel(
                tenant_id=db_interview.tenant_id,
                interview_id=db_interview.id,
                interviewer_id=interviewer_uuid,
                is_submitted=False
            )
            db.add(panel)
        db.commit()

    if not interview.skip_ai_questions:
        background_tasks.add_task(
            generate_questions_background,
            db_interview.tenant_id,
            db_interview.id,
            interview.question_bank_ids,
            interview.question_count or 5,
            interview_category
        )

    if not interview.skip_email:
        background_tasks.add_task(
            send_interview_invitation_background,
            db_interview.tenant_id,
            db_interview.id
        )

    return db_interview


@background_task_context
def send_interview_invitation_background(tenant_id: UUID, interview_id: UUID):
    """
    后台任务：发送面试邀请邮件
    """
    from app.services.mail_service import get_mail_service

    with tenant_session(tenant_id) as db:
        interview = db.query(Interview).filter(Interview.id == interview_id).first()
        if not interview:
            logger.warning(
                "Interview invitation resource not found",
                extra={"tenant_id": str(tenant_id), "resource_id": str(interview_id)},
            )
            return

        mail_service = get_mail_service(db)
        result = mail_service.send_interview_invitation_for_interview(interview)

        if result["success"]:
            logger.info(f"Interview invitation sent successfully for interview {interview_id}")
        else:
            logger.warning(f"Failed to send invitation for interview {interview_id}: {result['errors']}")

def export_interview_result(db: Session, interview_id: UUID, format: str = "markdown"):
    db_interview = db.query(Interview).options(
        joinedload(Interview.resume),
        joinedload(Interview.position)
    ).filter(Interview.id == interview_id).first()
    
    if not db_interview:
        return None
        
    candidate_name = db_interview.resume.candidate_name if db_interview.resume else "Candidate"
    position_title = db_interview.position.title if db_interview.position else "Position"
    
    # Always return Markdown
    content = f"# 面试评估报告\n\n"
    content += f"- **候选人**: {candidate_name}\n"
    content += f"- **应聘岗位**: {position_title}\n"
    content += f"- **面试时间**: {format_datetime_cn(db_interview.interview_time)}\n"
    content += f"- **面试结果**: {db_interview.result.value if db_interview.result else 'N/A'}\n"
    content += f"- **综合得分**: {db_interview.total_score if db_interview.total_score is not None else 'N/A'}\n\n"
    
    # AI初审评价
    if db_interview.resume:
        resume = db_interview.resume
        content += "## 简历初审评价\n\n"
        content += f"- **匹配度评分**: {resume.match_score if resume.match_score is not None else 'N/A'} 分\n"
        
        screening_result_text = '待定'
        if resume.screening_result:
            screening_map = {
                'passed': '通过',
                'rejected': '淘汰',
                'waitlist': '待定'
            }
            screening_result_text = screening_map.get(resume.screening_result.value if hasattr(resume.screening_result, 'value') else resume.screening_result, resume.screening_result)
        content += f"- **初审结果**: {screening_result_text}\n\n"
        
        if resume.ai_review:
            content += "**AI 评价**:\n\n"
            content += f"{resume.ai_review}\n\n"
        content += "---\n\n"
    
    content += "## 综合评价\n\n"
    content += f"{db_interview.evaluation or '暂无评价'}\n\n"

    transcripts = db_interview.transcripts or {}
    full_interview_data = transcripts.get("full_interview_data")
    full_interview_text = transcripts.get("full_interview", "")
    if isinstance(full_interview_text, dict):
        full_interview_text = full_interview_text.get("text", "")
    if not full_interview_text and isinstance(full_interview_data, dict):
        full_interview_text = full_interview_data.get("text", "")

    question_transcripts = []
    for key, value in transcripts.items():
        if key in {"full_interview", "full_interview_data"}:
            continue
        if isinstance(value, dict):
            value = value.get("text", "")
        if value:
            question_transcripts.append((str(key), str(value)))

    if full_interview_text or question_transcripts:
        content += "## 面试过程记录\n\n"
        if full_interview_text:
            content += f"{full_interview_text}\n\n"

        def transcript_sort_key(item):
            key = item[0]
            return (0, int(key)) if key.isdigit() else (1, key)

        for key, transcript in sorted(question_transcripts, key=transcript_sort_key):
            if key.isdigit():
                question_index = int(key)
                question = (db_interview.questions or [])
                question_title = (
                    question[question_index].get("title")
                    if question_index < len(question)
                    else None
                )
                label = f"第 {question_index + 1} 题"
                if question_title:
                    label += f"：{question_title}"
            else:
                label = key
            content += f"### {label}\n\n{transcript}\n\n"
    
    content += "## 详细评估\n\n"
    
    questions = db_interview.questions or []
    scores = db_interview.scores or {}
    comments = db_interview.comments or {}
    
    for i, q in enumerate(questions):
        idx = str(i)
        title = q.get('title', f'问题 {i+1}')
        score = scores.get(idx, 0)
        comment = comments.get(idx, '暂无评语')
        
        content += f"### {i+1}. {title}\n\n"
        content += f"**平均得分**: {score}/10\n\n"
        content += f"**问题内容**:\n{q.get('content', '')}\n\n"
        content += f"**参考答案**:\n{q.get('reference_answer', '')}\n\n"
        
        # Display aggregated comments or detailed panel breakdown
        # comments for aggregated interview is already formatted as "**Name**: comment"
        if comment:
             content += f"**面试官详细评语**:\n{comment}\n\n"
        else:
             content += f"**面试官评语**: 暂无\n\n"
             
        content += "---\n\n"
        
    return content

def get_interviews(db: Session, skip: int = 0, limit: int = 100, status: str = None):
    query = db.query(Interview).options(
        joinedload(Interview.resume),
        joinedload(Interview.position)
    )
    if status:
        query = query.filter(Interview.status == status)
    return query.offset(skip).limit(limit).all()

def get_interviews_for_interviewer(db: Session, interviewer_id: UUID, skip: int = 0, limit: int = 100):
    """
    Fetch interviews where the user is a panel member.
    Since panel_members is a JSON column storing a list of IDs, we need to filter in memory 
    or use dialect-specific JSON operators. For portability and simplicity with small datasets,
    we'll filter in Python. Ideally, use a many-to-many relationship table.
    """
    # Fetch all interviews (or a larger subset) and filter
    # Optimization: Filter by status if needed, but here we want all.
    all_interviews = db.query(Interview).options(
        joinedload(Interview.resume),
        joinedload(Interview.position)
    ).all()
    
    filtered = []
    str_id = str(interviewer_id)
    
    for interview in all_interviews:
        if interview.panel_members and str_id in [str(m) for m in interview.panel_members]:
            filtered.append(interview)
            
    # Apply skip/limit
    return filtered[skip: skip + limit]

def get_interview(db: Session, interview_id: UUID):
    return db.query(Interview).options(
        joinedload(Interview.resume),
        joinedload(Interview.position),
        joinedload(Interview.panels)
    ).filter(Interview.id == interview_id).first()

def update_interview(db: Session, interview_id: UUID, interview: InterviewUpdate):
    db_interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not db_interview:
        return None
    
    update_data = interview.dict(exclude_unset=True)
    for key, value in update_data.items():
        if key == "interview_time":
            value = _normalize_dt_utc(value)
        setattr(db_interview, key, value)
    
    db.commit()
    db.refresh(db_interview)
    return db_interview


def update_interview_schedule(
    db: Session,
    interview_id: UUID,
    schedule: InterviewScheduleUpdate,
):
    db_interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not db_interview:
        return None
    if db_interview.lifecycle_state != "scheduled" or db_interview.status != InterviewStatus.SCHEDULED:
        raise HTTPException(status_code=409, detail="只能修改尚未开始的面试安排")

    member_ids = list(schedule.panel_members)
    assignable_roles = [UserRole.ADMIN, UserRole.HR, UserRole.INTERVIEWER]
    users = db.query(User).filter(
        User.id.in_(member_ids),
        User.is_active == True,
        User.role.in_(assignable_roles),
    ).all()
    users_by_id = {user.id: user for user in users}
    missing_ids = [str(member_id) for member_id in member_ids if member_id not in users_by_id]
    if missing_ids:
        raise HTTPException(status_code=422, detail="面试官不存在、已停用或不可分配")

    new_member_set = set(member_ids)
    existing_panels = {
        panel.interviewer_id: panel
        for panel in db.query(InterviewPanel).filter(InterviewPanel.interview_id == interview_id).all()
    }

    for existing_id, panel in existing_panels.items():
        if existing_id not in new_member_set:
            db.delete(panel)
    for added_id in new_member_set - set(existing_panels):
        db.add(InterviewPanel(
            tenant_id=db_interview.tenant_id,
            interview_id=db_interview.id,
            interviewer_id=added_id,
            is_submitted=False,
        ))

    db_interview.panel_members = [str(member_id) for member_id in member_ids]
    db_interview.interviewer = "面试小组"
    db_interview.interview_time = _normalize_dt_utc(schedule.interview_time)
    db_interview.interview_type = schedule.interview_type
    db_interview.interview_location = (
        schedule.interview_location.strip()
        if schedule.interview_type == "onsite" and schedule.interview_location
        else None
    )
    db_interview.meeting_link = (
        schedule.meeting_link.strip()
        if schedule.interview_type == "video" and schedule.meeting_link
        else None
    )
    db.commit()
    db.refresh(db_interview)
    return db_interview

def update_interview_questions(db: Session, interview_id: UUID, questions: list):
    db_interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not db_interview:
        return None
    
    db_interview.questions = questions
    db.commit()
    db.refresh(db_interview)
    return db_interview

def delete_interview(db: Session, interview_id: UUID):
    db_interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not db_interview:
        return None

    deletable = (
        db_interview.lifecycle_state == "cancelled"
        or (
            db_interview.lifecycle_state == "scheduled"
            and db_interview.status == InterviewStatus.SCHEDULED
        )
    )
    if not deletable:
        raise HTTPException(status_code=409, detail="Only scheduled or cancelled interviews can be deleted")

    restore_after_cancellation(db, db_interview)
    tenant_id = db_interview.tenant_id
    file_locations = stage_file_deletions(
        db, tenant_resource_files(
            db, tenant_id, "interview", interview_id, "interview_audio"
        )
    )
    db.delete(db_interview)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    unlink_file_locations(file_locations, root=UPLOAD_ROOT)
    return db_interview

def cancel_interview(db: Session, interview_id: UUID, reason: str = None):
    """
    取消面试，将状态改为 CANCELLED。
    只有 SCHEDULED 或 IN_PROGRESS 状态的面试可以取消。
    """
    db_interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not db_interview:
        return None

    cleaned_reason = (reason or "").strip()
    if not cleaned_reason:
        raise HTTPException(status_code=422, detail="Cancellation reason is required")

    if db_interview.lifecycle_state != "scheduled" or db_interview.status != InterviewStatus.SCHEDULED:
        raise HTTPException(status_code=409, detail="Only scheduled interviews can be cancelled")

    db_interview.status = InterviewStatus.CANCELLED
    db_interview.lifecycle_state = "cancelled"
    db_interview.cancel_reason = cleaned_reason
    db_interview.cancelled_at = datetime.now(timezone.utc)
    db_interview.comments = {
        **(db_interview.comments or {}),
        "cancel_reason": cleaned_reason,
    }
    restore_after_cancellation(db, db_interview)

    db.commit()
    db.refresh(db_interview)
    print(f"Interview {interview_id} cancelled")
    return db_interview

def get_submission_status(db: Session, interview_id: UUID):
    """
    获取面试的评分提交状态。
    返回各面试官是否已提交评分。
    """
    db_interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not db_interview:
        return None

    panel_members = db_interview.panel_members or []
    panels = db.query(InterviewPanel).filter(
        InterviewPanel.interview_id == interview_id
    ).all()

    submission_status = {}
    for member_id in panel_members:
        # 将字符串 ID 转换为 UUID 进行查询
        try:
            member_uuid = UUID(member_id) if isinstance(member_id, str) else member_id
        except (ValueError, TypeError):
            member_uuid = member_id

        member_panel = next(
            (p for p in panels if str(p.interviewer_id) == str(member_id)),
            None
        )
        interviewer = db.query(User).filter(User.id == member_uuid).first()
        submission_status[str(member_id)] = {
            "name": interviewer.full_name if interviewer else "Unknown",
            "submitted": member_panel.is_submitted if member_panel else False,
            "submitted_at": member_panel.updated_at if member_panel and member_panel.is_submitted else None
        }

    return {
        "interview_id": str(interview_id),
        "total_members": len(panel_members),
        "submitted_count": sum(1 for s in submission_status.values() if s["submitted"]),
        "members": submission_status
    }

@background_task_context
def generate_evaluation_background(tenant_id: UUID, interview_id: UUID, score_data: dict):
    with tenant_session(tenant_id) as db:
        return _generate_evaluation_background(db, interview_id, score_data)


def _generate_evaluation_background(db: Session, interview_id: UUID, score_data: dict):
    try:
        db_interview = db.query(Interview).filter(Interview.id == interview_id).first()
        if not db_interview:
            logger.warning(
                "Interview evaluation resource not found",
                extra={"resource_id": str(interview_id)},
            )
            return
        
        if db_interview.status != InterviewStatus.ANALYZING:
            db_interview.status = InterviewStatus.ANALYZING
        mark_legacy_interview_ended(db_interview)
        db.commit()
            
        scores = score_data.get('scores', {})
        panel_details = score_data.get('panel_details', "")
        transcripts = score_data.get('transcripts', "")
        
        if not scores:
            db_interview.result = InterviewResult.PENDING
            mark_legacy_interview_completed(db_interview)
            db.commit()
            return

        count = len(scores)
        total_sum = sum(scores.values())
        average_score = round(total_sum / count) if count > 0 else 0
        
        db_interview.total_score = average_score
        
        try:
            questions = db_interview.questions or []
            evaluation_result = generate_interview_evaluation(
                questions,
                scores,
                average_score,
                panel_details=panel_details,
                transcripts=transcripts,
                db=db,
            )
            db_interview.evaluation = evaluation_result.get("evaluation")
            db_interview.suggestion = evaluation_result.get("suggestion")
        except Exception:
            print(f"Evaluation generation failed for interview {interview_id}")
            db_interview.evaluation = "AI评价生成失败，请手动填写评价"
            db_interview.suggestion = "waitlist"
        
        db_interview.result = InterviewResult.PENDING
        mark_legacy_interview_completed(db_interview)
        
        db.commit()
        
    except Exception:
        db.rollback()
        logger.error(
            "Interview evaluation failed",
            extra={"resource_id": str(interview_id)},
        )
        raise RuntimeError("interview background task failed") from None


@background_task_context
def generate_combined_evaluation(tenant_id: UUID, interview_id: UUID, transcript: str, interviewer_evaluation: str, interviewer_suggestion: str, interviewer_score: int):
    """
    后台任务：结合录音转写和面试官评价生成综合评价
    """
    from app.services.ai_service import generate_interview_evaluation_from_transcript
    
    with tenant_session(tenant_id) as db:
        db_interview = db.query(Interview).filter(Interview.id == interview_id).first()
        if not db_interview:
            logger.warning(
                "Combined interview evaluation resource not found",
                extra={"tenant_id": str(tenant_id), "resource_id": str(interview_id)},
            )
            return
        
        if db_interview.status != InterviewStatus.ANALYZING:
            db_interview.status = InterviewStatus.ANALYZING
        mark_legacy_interview_ended(db_interview)
        db.commit()
        
        try:
            evaluation_result = generate_interview_evaluation_from_transcript(
                transcript,
                interviewer_evaluation,
                interviewer_score,
                db=db,
            )
            db_interview.evaluation = evaluation_result.get("evaluation", interviewer_evaluation)
            db_interview.suggestion = evaluation_result.get("suggestion", interviewer_suggestion)
        except Exception:
            print("Combined evaluation generation failed")
            db_interview.evaluation = interviewer_evaluation
            db_interview.suggestion = interviewer_suggestion
        
        db_interview.result = InterviewResult.PENDING
        mark_legacy_interview_completed(db_interview)
        db.commit()


def confirm_interview_result(db: Session, interview_id: UUID, result: str, background_tasks: BackgroundTasks = None):
    db_interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not db_interview:
        return None

    # 更新结果和状态
    # result string comes from frontend as 'passed', 'rejected', 'waitlist', 'hired', 'next_round' (lowercase)
    # InterviewResult enum members are PASSED, REJECTED, WAITLIST, HIRED, NEXT_ROUND (uppercase)
    result_upper = result.upper()

    if result_upper in InterviewResult.__members__:
        db_interview.result = InterviewResult[result_upper]
    else:
        # Fallback or error handling
        print(f"Invalid result value: {result}")
        return None

    mark_legacy_interview_completed(db_interview)

    # 同步更新简历状态
    if db_interview.resume_id:
        resume = db.query(Resume).filter(Resume.id == db_interview.resume_id).first()
        if resume:
            # 录用 - 面试通过，等待发Offer
            if db_interview.result == InterviewResult.HIRED:
                resume.status = ResumeStatus.OFFER_PENDING
                resume.screening_result = ScreeningResult.PASSED
            # 进入下一轮 - 简历保持待面试状态，可以安排下一轮面试
            elif db_interview.result == InterviewResult.NEXT_ROUND:
                resume.status = ResumeStatus.PENDING_INTERVIEW
                resume.screening_result = ScreeningResult.PASSED
            # 通过 - 面试通过，等待后续安排
            elif db_interview.result == InterviewResult.PASSED:
                resume.status = ResumeStatus.INTERVIEW_PASSED
                resume.screening_result = ScreeningResult.PASSED
            # 淘汰
            elif db_interview.result == InterviewResult.REJECTED:
                resume.status = ResumeStatus.INTERVIEW_FAILED
                resume.screening_result = ScreeningResult.REJECTED
            # 待定
            elif db_interview.result == InterviewResult.WAITLIST:
                resume.status = ResumeStatus.WAITLIST
                resume.screening_result = ScreeningResult.WAITLIST

            # Commit explicitly for resume if needed, but db.commit() below handles all changes in session

    apply_final_decision(db_interview)
    db.commit()
    db.refresh(db_interview)

    return db_interview


@background_task_context
def send_result_notification_background(tenant_id: UUID, interview_id: UUID):
    """
    后台任务：发送面试结果通知邮件
    """
    from app.services.mail_service import get_mail_service

    with tenant_session(tenant_id) as db:
        interview = db.query(Interview).filter(Interview.id == interview_id).first()
        if not interview:
            logger.warning(
                "Interview result notification resource not found",
                extra={"tenant_id": str(tenant_id), "resource_id": str(interview_id)},
            )
            return

        mail_service = get_mail_service(db)
        result = mail_service.send_result_notification_for_interview(interview)

        if result["success"]:
            logger.info(f"Result notification sent successfully for interview {interview_id}")
        else:
            logger.warning(f"Failed to send result notification for interview {interview_id}: {result.get('error')}")

def submit_interview_score(
    db: Session,
    interview_id: UUID,
    interviewer_id: UUID,
    score_data: InterviewScore,
    background_tasks: BackgroundTasks,
    *,
    actor: User | None = None,
):
    """
    统一的评分提交函数，单面试官和多面试官都使用此函数。
    """
    db_interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not db_interview:
        return None

    authorized = (
        can_score_interview(db, db_interview, actor)
        if actor is not None and actor.id == interviewer_id
        else is_interviewer_assigned(db, db_interview, interviewer_id)
    )
    if not authorized:
        raise HTTPException(status_code=403, detail="Interview assignment required")

    if db_interview.status == InterviewStatus.SCHEDULED:
        db_interview.status = InterviewStatus.IN_PROGRESS
        db.commit()

    avg_score = sum(score_data.scores.values()) // len(score_data.scores) if score_data.scores else 0

    panel = db.query(InterviewPanel).filter(
        InterviewPanel.interview_id == interview_id,
        InterviewPanel.interviewer_id == interviewer_id
    ).first()

    if not panel:
        panel = InterviewPanel(
            tenant_id=db_interview.tenant_id,
            interview_id=interview_id,
            interviewer_id=interviewer_id,
            scores=score_data.scores,
            comments=score_data.comments,
            total_score=avg_score,
            is_submitted=True
        )
        db.add(panel)
    else:
        panel.scores = score_data.scores
        panel.comments = score_data.comments
        panel.total_score = avg_score
        panel.is_submitted = True

    db.commit()
    db.refresh(panel)

    db_interview.scores = score_data.scores
    db_interview.comments = score_data.comments
    db_interview.total_score = avg_score
    db_interview.status = InterviewStatus.ANALYZING
    db_interview.result = InterviewResult.PENDING
    mark_legacy_interview_ended(db_interview)
    db.commit()
    db.refresh(db_interview)
    
    background_tasks.add_task(
        generate_evaluation_background,
        db_interview.tenant_id,
        db_interview.id,
        {
            "scores": score_data.scores,
            "panel_details": "",
            "transcripts": ""
        }
    )
    
    return db_interview
