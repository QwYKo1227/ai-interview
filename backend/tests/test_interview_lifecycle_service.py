from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.file_models import StoredFile
from app.models.models import (
    Interview,
    InterviewPanel,
    InterviewStatus,
    ResumeStatus,
    ScreeningResult,
    User,
    UserRole,
)
from app.services import interview_lifecycle_service
from app.services.interview_lifecycle_service import (
    SCORE_DIMENSIONS,
    confirm_final_decision,
    correct_final_decision,
    confirm_recording,
    append_recording_chunk,
    enforce_analysis_contract,
    force_end_interview,
    persist_realtime_transcript,
    reserve_recording,
    submit_human_review,
    process_asr_job,
    utcnow,
)
from app.services.interview_lifecycle_monitor import (
    release_expired_recording_reservations_for_tenant,
)
from app.services.resume_interview_status import mark_legacy_interview_completed


def test_remux_seekable_webm_replaces_source_atomically(tmp_path, monkeypatch):
    source = tmp_path / "recording.webm"
    source.write_bytes(b"raw-webm")
    captured = {}

    monkeypatch.setattr(interview_lifecycle_service.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        Path(command[-1]).write_bytes(b"seekable-webm")

    monkeypatch.setattr(interview_lifecycle_service.subprocess, "run", fake_run)

    interview_lifecycle_service.remux_seekable_webm(source)

    assert source.read_bytes() == b"seekable-webm"
    assert captured["command"][captured["command"].index("-c:a") + 1] == "copy"
    assert captured["kwargs"]["check"] is True
    assert not list(tmp_path.glob("*.seekable.webm"))


def test_recording_reservation_only_starts_interview_after_confirmation(
    db: Session,
    test_interview,
    test_interviewer,
):
    reserved = reserve_recording(db, test_interview.id, test_interviewer)

    assert reserved.recording_state == "reserved"
    assert reserved.lifecycle_state == "scheduled"

    started = confirm_recording(
        db,
        test_interview.id,
        reserved.recording_session_id,
        test_interviewer,
    )

    assert started.recording_state == "recording"
    assert started.lifecycle_state == "in_progress"
    assert started.started_at is not None
    assert started.resume.status.value == "interview_in_progress"


def test_expired_recording_reservation_is_released(
    db: Session,
    test_interview,
    test_interviewer,
    monkeypatch,
):
    test_interview.lifecycle_state = "scheduled"
    test_interview.recording_state = "reserved"
    test_interview.recording_session_id = uuid4()
    test_interview.recording_owner_id = test_interviewer.id
    test_interview.recording_reservation_expires_at = utcnow() - timedelta(days=1)
    test_interview.recording_heartbeat_at = utcnow() - timedelta(days=1)
    db.commit()

    @contextmanager
    def test_tenant_session(_tenant_id):
        yield db

    monkeypatch.setattr(
        "app.services.interview_lifecycle_monitor.tenant_session",
        test_tenant_session,
    )

    released = release_expired_recording_reservations_for_tenant(test_interview.tenant_id)

    db.refresh(test_interview)
    assert released == 1
    assert test_interview.lifecycle_state == "scheduled"
    assert test_interview.recording_state == "idle"
    assert test_interview.recording_session_id is None
    assert test_interview.recording_owner_id is None
    assert test_interview.recording_reservation_expires_at is None
    assert test_interview.recording_heartbeat_at is None


def test_recording_reservation_rejects_interview_before_scheduled_time(
    db: Session,
    test_interview,
    test_interviewer,
):
    test_interview.interview_time = utcnow() + timedelta(minutes=20)
    db.commit()

    with pytest.raises(HTTPException) as error:
        reserve_recording(db, test_interview.id, test_interviewer)

    assert error.value.status_code == 409
    assert "面试尚未到开始时间" in error.value.detail
    assert test_interview.recording_state == "idle"


def test_recording_confirmation_rechecks_rescheduled_start_time(
    db: Session,
    test_interview,
    test_interviewer,
):
    test_interview.interview_time = utcnow() - timedelta(minutes=1)
    db.commit()
    reserved = reserve_recording(db, test_interview.id, test_interviewer)
    session_id = reserved.recording_session_id

    test_interview.interview_time = utcnow() + timedelta(minutes=20)
    db.commit()

    with pytest.raises(HTTPException) as error:
        confirm_recording(db, test_interview.id, session_id, test_interviewer)

    assert error.value.status_code == 409
    assert "面试尚未到开始时间" in error.value.detail
    assert test_interview.lifecycle_state == "scheduled"


def test_live_recording_reservation_rejects_another_interviewer(
    db: Session,
    tenant_a,
    test_interview,
    test_interviewer,
):
    another = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email="second-interviewer@example.com",
        hashed_password="not-used",
        role=UserRole.INTERVIEWER,
        is_active=True,
    )
    db.add(another)
    test_interview.panel_members = [str(test_interviewer.id), str(another.id)]
    db.commit()

    reserve_recording(db, test_interview.id, test_interviewer)

    with pytest.raises(HTTPException) as error:
        reserve_recording(db, test_interview.id, another)

    assert error.value.status_code == 409


def test_recording_chunks_cannot_exceed_total_recording_limit(
    db: Session,
    test_interview,
    test_interviewer,
    monkeypatch,
):
    session_id = uuid4()
    test_interview.lifecycle_state = "in_progress"
    test_interview.recording_state = "recording"
    test_interview.recording_session_id = session_id
    test_interview.recording_owner_id = test_interviewer.id
    test_interview.recording_chunks = [
        {
            "index": 0,
            "file_id": str(uuid4()),
            "size": interview_lifecycle_service.MAX_RECORDING_SIZE,
        }
    ]
    db.commit()

    staged = StoredFile(
        id=uuid4(),
        tenant_id=test_interview.tenant_id,
        object_key=f"{test_interview.tenant_id}/interview_audio/overflow.webm",
        original_filename="overflow.webm",
        content_type="video/webm",
        size=1,
        category="interview_audio",
        resource_type="interview_recording_chunk",
        resource_id=test_interview.id,
    )
    cleaned = []
    monkeypatch.setattr(
        interview_lifecycle_service,
        "cleanup_new_file",
        lambda db, record: cleaned.append(record.id),
    )

    with pytest.raises(HTTPException) as error:
        append_recording_chunk(
            db,
            test_interview.id,
            session_id,
            1,
            staged,
            test_interviewer,
        )

    assert error.value.status_code == 413
    assert cleaned == [staged.id]


def test_realtime_transcript_segments_are_persisted_idempotently(
    db: Session,
    test_interview,
    test_interviewer,
):
    session_id = uuid4()
    test_interview.lifecycle_state = "in_progress"
    test_interview.recording_state = "recording"
    test_interview.recording_session_id = session_id
    test_interview.recording_owner_id = test_interviewer.id
    db.commit()

    first = persist_realtime_transcript(
        db,
        test_interview.id,
        session_id,
        [{"id": "session-1:1", "text": "第一段", "speaker": "speaker_0"}],
        test_interviewer,
    )
    repeated = persist_realtime_transcript(
        db,
        test_interview.id,
        session_id,
        [
            {"id": "session-1:1", "text": "第一段", "speaker": "speaker_0"},
            {"id": "session-1:2", "text": "第二段", "speaker": "speaker_1"},
        ],
        test_interviewer,
    )

    db.refresh(test_interview)
    assert first == {"accepted": 1, "total": 1}
    assert repeated == {"accepted": 1, "total": 2}
    assert test_interview.transcripts["realtime_full_interview"] == "第一段\n第二段"
    assert [
        item["id"]
        for item in test_interview.transcripts["realtime_full_interview_data"]["segments"]
    ] == ["session-1:1", "session-1:2"]


def test_admin_can_force_end_interview_without_recording_session(
    db: Session,
    test_interview,
    test_interview_panel: InterviewPanel,
    test_admin,
):
    test_interview.lifecycle_state = "in_progress"
    test_interview.recording_state = "idle"
    test_interview.status = InterviewStatus.IN_PROGRESS
    db.commit()

    ended = force_end_interview(
        db,
        test_interview.id,
        test_admin,
        "Candidate left before recording started",
    )

    assert ended.lifecycle_state == "ended"
    assert ended.recording_state == "failed"
    assert ended.status.value == "completed"
    assert ended.ended_at is not None
    assert ended.notes_revealed_at == ended.ended_at
    assert ended.end_reason == "Candidate left before recording started"
    assert ended.ai_analysis_status == "failed"
    assert ended.resume.status.value == "pending_interview_result"
    assert test_interview_panel.notes_frozen_at == ended.ended_at


def test_interviewer_cannot_force_end_interview(
    db: Session,
    test_interview,
    test_interviewer,
):
    test_interview.lifecycle_state = "in_progress"
    db.commit()

    with pytest.raises(HTTPException) as error:
        force_end_interview(
            db,
            test_interview.id,
            test_interviewer,
            "Not authorized",
        )

    assert error.value.status_code == 403


def test_legacy_evaluation_completion_synchronizes_lifecycle_and_resume(
    db: Session,
    test_interview,
    test_interview_panel: InterviewPanel,
):
    test_interview.lifecycle_state = "in_progress"
    test_interview.recording_state = "idle"
    test_interview.status = InterviewStatus.ANALYZING
    test_interview.evaluation = "Legacy evaluation"
    db.commit()

    mark_legacy_interview_completed(test_interview)
    db.commit()

    assert test_interview.status == InterviewStatus.COMPLETED
    assert test_interview.lifecycle_state == "ended"
    assert test_interview.ended_at is not None
    assert test_interview.notes_revealed_at == test_interview.ended_at
    assert test_interview.ai_analysis_status == "not_applicable"
    assert test_interview.asr_job_status == "not_applicable"
    assert test_interview.resume.status.value == "pending_interview_result"
    assert test_interview_panel.notes_frozen_at == test_interview.ended_at


def test_human_review_is_independent_and_required_for_final_decision(
    db: Session,
    test_interview,
    test_interviewer,
    test_interview_panel: InterviewPanel,
    test_user,
):
    test_interview.lifecycle_state = "ended"
    db.commit()
    scores = {key: 8 for key in SCORE_DIMENSIONS}

    panel = submit_human_review(
        db,
        test_interview,
        test_interviewer,
        scores,
        "Strong evidence across the interview.",
        "next_round",
    )

    assert panel.human_scores == scores
    assert panel.human_review_submitted_at is not None
    assert test_interview.ai_analysis is None

    decided = confirm_final_decision(db, test_interview, test_user, "next_round")

    assert decided.result.value == "next_round"
    assert decided.final_decision_by == test_user.id
    assert decided.final_decision_at is not None
    assert test_interview.resume.status.value == "pending_next_interview"


def test_final_decision_updates_resume_scheduled_from_pending_review(
    db: Session,
    test_interview,
    test_interview_panel: InterviewPanel,
    test_user,
):
    test_interview.lifecycle_state = "ended"
    test_interview.resume.status = ResumeStatus.PENDING_REVIEW
    test_interview.resume.screening_result = ScreeningResult.WAITLIST
    test_interview_panel.human_review_submitted_at = utcnow()
    db.commit()

    decided = confirm_final_decision(db, test_interview, test_user, "passed")

    assert decided.resume.status == ResumeStatus.INTERVIEW_PASSED
    assert decided.resume.screening_result == ScreeningResult.PASSED


def test_ai_contract_requires_timestamp_evidence_and_enforces_gates():
    transcript_data = {
        "segments": [{"start": 1.0, "end": 2.0, "text": "evidence"}],
    }
    dimensions = {
        key: {
            "score": 8,
            "assessment": "Supported",
            "evidence": [{"start": 1.0, "end": 2.0, "quote": "evidence"}],
        }
        for key in SCORE_DIMENSIONS
    }
    dimensions["technical_fit"]["score"] = 5
    dimensions["culture_fit"]["score"] = None
    dimensions["culture_fit"]["evidence"] = []

    result = enforce_analysis_contract({
        "format_version": 2,
        "dimensions": dimensions,
        "recommendation": "passed",
        "summary": "候选人的回答能够覆盖多数评分维度，但关键技术 Gate 的论述深度未达到通过标准，需要结合目标岗位要求继续验证具体实现细节和复杂场景下的判断能力。",
        "strengths": [{
            "conclusion": "能够给出相关回答",
            "evidence": {"start": 1.0, "end": 2.0, "quote": "evidence"},
            "job_impact": "具备继续验证岗位匹配度的基础",
        }],
        "risks": [{
            "conclusion": "技术深度未达到 Gate",
            "evidence": {"start": 1.0, "end": 2.0, "quote": "evidence"},
            "job_impact": "可能影响复杂任务的独立交付",
        }],
        "recommendation_reason": "关键技术 Gate 低于阈值，当前不宜直接通过；建议在后续环节围绕实际实现细节、异常处理和复杂场景决策进行针对性验证后再作判断。",
        "next_round_questions": ["请说明复杂场景下的具体实现和异常处理。"],
    }, transcript_data)

    assert result["recommendation"] == "waitlist"
    assert result["dimensions"]["culture_fit"]["score"] is None
    assert result["coverage"] == 95


def test_ai_contract_rejects_finding_evidence_not_found_in_transcript():
    dimensions = {
        key: {
            "score": 8,
            "assessment": "Supported",
            "evidence": [{"start": 1.0, "end": 2.0, "quote": "真实回答"}],
        }
        for key in SCORE_DIMENSIONS
    }
    with pytest.raises(ValueError, match="证据与录音转写"):
        enforce_analysis_contract({
            "format_version": 2,
            "dimensions": dimensions,
            "recommendation": "passed",
            "summary": "综合表现说明",
            "strengths": [{
                "conclusion": "虚构优势",
                "evidence": {"start": 1.0, "end": 2.0, "quote": "不存在的回答"},
                "job_impact": "虚构影响",
            }],
            "risks": [],
            "recommendation_reason": "录用建议说明",
            "next_round_questions": [],
        }, {"segments": [{"start": 1.0, "end": 2.0, "text": "真实回答"}]})


def test_admin_can_correct_locked_final_decision_with_audit(
    db: Session,
    test_interview,
    test_interviewer,
    test_interview_panel: InterviewPanel,
    test_user,
    test_admin,
):
    test_interview.lifecycle_state = "ended"
    test_interview_panel.human_review_submitted_at = utcnow()
    db.commit()
    confirm_final_decision(db, test_interview, test_user, "passed")

    corrected = correct_final_decision(
        db,
        test_interview,
        test_admin,
        "rejected",
        "Decision entered against the wrong candidate",
    )

    assert corrected.result.value == "rejected"
    assert corrected.resume.status.value == "interview_failed"
    assert corrected.decision_history[-1]["from"] == "passed"
    assert corrected.decision_history[-1]["to"] == "rejected"
    assert corrected.decision_history[-1]["reason"] == "Decision entered against the wrong candidate"


def test_async_asr_job_is_persisted_completed_and_deleted(
    db: Session,
    tmp_path,
    monkeypatch,
    test_interview: Interview,
):
    audio_path = tmp_path / "full.webm"
    audio_path.write_bytes(b"recording")
    stored = StoredFile(
        tenant_id=test_interview.tenant_id,
        object_key=f"{test_interview.tenant_id}/interview_audio/full.webm",
        original_filename="full.webm",
        content_type="audio/webm",
        size=9,
        category="interview_audio",
        resource_type="interview",
        resource_id=test_interview.id,
    )
    db.add(stored)
    db.flush()
    test_interview.lifecycle_state = "ended"
    test_interview.recording_state = "sealed"
    test_interview.audio_records = {"full_interview": f"/api/files/{stored.id}"}
    test_interview.asr_job_status = "pending"
    test_interview.asr_job_next_poll_at = utcnow()
    db.commit()

    monkeypatch.setattr(interview_lifecycle_service, "stored_file_path", lambda _record: audio_path)
    monkeypatch.setattr(
        interview_lifecycle_service,
        "get_transcription_config",
        lambda _db: {
            "provider": "openai_compatible",
            "base_url": "http://asr.test/v1",
            "model": "paraformer-offline",
            "api_key": "secret",
        },
    )
    monkeypatch.setattr(
        interview_lifecycle_service,
        "create_transcription_job",
        lambda _path, _config: {"id": "job-1", "status": "queued"},
    )

    process_asr_job(test_interview.tenant_id, test_interview.id)
    db.expire_all()
    current = db.query(Interview).filter(Interview.id == test_interview.id).one()
    assert current.asr_job_id == "job-1"
    assert current.asr_job_status == "queued"
    assert current.asr_job_attempts == 1

    current.asr_job_next_poll_at = utcnow() - timedelta(seconds=1)
    db.commit()
    deleted = []
    analyzed = []
    monkeypatch.setattr(
        interview_lifecycle_service,
        "get_transcription_job",
        lambda _job_id, _config: {
            "id": "job-1",
            "status": "completed",
            "result": {
                "text": "正式离线转写",
                "segments": [{
                    "speaker": "speaker_0",
                    "text": "正式离线转写",
                    "start": 0,
                    "end": 1,
                }],
                "model": "paraformer-offline",
            },
        },
    )
    monkeypatch.setattr(
        interview_lifecycle_service,
        "delete_transcription_job",
        lambda job_id, _config: deleted.append(job_id),
    )
    monkeypatch.setattr(
        interview_lifecycle_service,
        "analyze_sealed_recording",
        lambda tenant_id, interview_id: analyzed.append((tenant_id, interview_id)),
    )

    process_asr_job(test_interview.tenant_id, test_interview.id)
    db.expire_all()
    current = db.query(Interview).filter(Interview.id == test_interview.id).one()
    assert current.asr_job_status == "completed"
    assert current.asr_job_id is None
    assert current.asr_job_delete_pending is False
    assert current.transcripts["full_interview"] == "正式离线转写"
    assert deleted == ["job-1"]
    assert analyzed == [(test_interview.tenant_id, test_interview.id)]
