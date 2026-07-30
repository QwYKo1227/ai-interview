from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.file_models import StoredFile
from app.models.models import Interview, InterviewPanel, InterviewStatus, User, UserRole
from app.services import interview_lifecycle_service
from app.services.interview_lifecycle_service import (
    SCORE_DIMENSIONS,
    confirm_final_decision,
    correct_final_decision,
    confirm_recording,
    enforce_analysis_contract,
    force_end_interview,
    reserve_recording,
    submit_human_review,
    process_asr_job,
    utcnow,
)


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


def test_ai_contract_requires_timestamp_evidence_and_enforces_gates():
    dimensions = {
        key: {
            "score": 8,
            "assessment": "Supported",
            "evidence": [{"start": 1.0, "end": 2.0, "quote": "evidence"}],
        }
        for key in SCORE_DIMENSIONS
    }
    dimensions["technical_fit"]["score"] = 5
    dimensions["culture_fit"]["evidence"] = []

    result = enforce_analysis_contract({
        "dimensions": dimensions,
        "recommendation": "passed",
    })

    assert result["recommendation"] == "waitlist"
    assert result["dimensions"]["culture_fit"]["score"] is None
    assert result["coverage"] == 95


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
