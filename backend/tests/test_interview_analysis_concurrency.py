"""Exercise analysis through both the request and recovery-task entry points."""

import json
import pytest
from sqlalchemy.orm import Session

from app.models.models import Interview
from app.services import interview_lifecycle_monitor as monitor
from app.services import interview_lifecycle_service as service


def analysis_response(text, score=6.2):
    return json.dumps({
        "format_version": 2,
        "dimensions": {
            key: {
                "score": score,
                "assessment": "具备相关经验",
                "evidence": [{"start": 0, "end": 1, "quote": text}],
            }
            for key in service.SCORE_DIMENSIONS
        },
        "recommendation": "next_round",
        "summary": "具备相关经验",
        "strengths": [],
        "risks": [],
        "recommendation_reason": "证据充分",
        "next_round_questions": [],
    })


@pytest.fixture
def analysis_interview(db, test_interview, monkeypatch):
    text = "我独立负责安全管理。"
    test_interview.lifecycle_state = "ended"
    test_interview.audio_records = {"full_interview": "/api/files/mock"}
    test_interview.asr_job_status = "completed"
    test_interview.asr_job_next_poll_at = None
    test_interview.transcripts = {
        "full_interview": text,
        "full_interview_data": {
            "source": "imported",
            "text": text,
            "segments": [{"start": 0, "end": 1, "text": text}],
        },
    }
    test_interview.ai_analysis_status = "pending"
    db.commit()
    monkeypatch.setattr(service, "get_transcription_config", lambda _db: {"provider": "openai_compatible"})
    monkeypatch.setattr(service.prompt_manager, "get_prompt", lambda *a, **kw: {"user": kw["transcript_data"], "system": "system"})
    return test_interview


def test_recovery_cannot_change_score_while_request_analysis_is_running(
    db, analysis_interview, monkeypatch,
):
    tenant_id, interview_id = analysis_interview.tenant_id, analysis_interview.id
    model_calls = []

    def generate(prompt, **kwargs):
        model_calls.append(prompt)
        score = 6.2 if len(model_calls) == 1 else 3.8
        if len(model_calls) == 1:
            monitor.resume_asr_jobs_for_tenant(tenant_id)
        return analysis_response(json.loads(prompt)["text"], score)

    monkeypatch.setattr(service, "generate_text", generate)
    service.analyze_sealed_recording(tenant_id, interview_id)

    db.expire_all()
    current = db.query(Interview).filter(Interview.id == interview_id).one()
    assert len(model_calls) == 1, "Recovery started a second scorer during the first analysis"
    assert current.ai_analysis["weighted_score"] == 6.2
    assert current.ai_analysis_version == 1


def test_completed_analysis_is_not_reexecuted_by_a_duplicate_callback(
    db, analysis_interview, monkeypatch,
):
    calls = []

    def generate(prompt, **kwargs):
        calls.append(prompt)
        return analysis_response(json.loads(prompt)["text"], 6.2 if len(calls) == 1 else 3.8)

    monkeypatch.setattr(service, "generate_text", generate)
    for _ in range(2):
        service.analyze_sealed_recording(analysis_interview.tenant_id, analysis_interview.id)
    db.expire_all()
    current = db.query(Interview).filter(Interview.id == analysis_interview.id).one()
    assert current.ai_analysis["weighted_score"] == 6.2
    assert current.ai_analysis_version == 1
    assert len(calls) == 1


@pytest.mark.parametrize("old_task_fails", [False, True])
def test_new_transcript_supersedes_active_analysis_and_is_recovered_without_audio(
    db, analysis_interview, monkeypatch, old_task_fails,
):
    tenant_id, interview_id = analysis_interview.tenant_id, analysis_interview.id
    old_text = analysis_interview.transcripts["full_interview"]
    new_text = "我独立完成消防改造和合规验收。"
    analysis_interview.ai_analysis = {"weighted_score": 6.2}
    analysis_interview.ai_analysis_version = 4
    db.commit()
    calls = []

    def generate(prompt, **kwargs):
        text = json.loads(prompt)["text"]
        calls.append(text)
        if text == old_text:
            # A separate HTTP request saves a correction while the model runs.
            with Session(db.get_bind()) as request_db:
                current = request_db.get(Interview, interview_id)
                current.transcripts = {
                    **current.transcripts,
                    "corrected_full_interview_data": {
                        "text": new_text,
                        "segments": [{"start": 0, "end": 1, "text": new_text}],
                    },
                }
                current.audio_records = None
                current.ai_analysis_status = "pending"
                request_db.commit()
            # The new callback must skip the busy worker. Recovery picks it up.
            service.analyze_sealed_recording(tenant_id, interview_id, True)
            if old_task_fails:
                raise RuntimeError("old model call failed")
            return analysis_response(text, 3.8)
        return analysis_response(text, 8)

    monkeypatch.setattr(service, "generate_text", generate)
    service.analyze_sealed_recording(tenant_id, interview_id)
    db.expire_all()
    current = db.get(Interview, interview_id)
    assert current.ai_analysis_status == "pending"
    assert current.ai_analysis["weighted_score"] == 6.2
    assert current.ai_analysis_version == 4
    assert current.transcripts["corrected_full_interview_data"]["text"] == new_text

    monitor.resume_asr_jobs_for_tenant(tenant_id)

    db.expire_all()
    current = db.get(Interview, interview_id)
    assert calls == [old_text, new_text]
    assert current.ai_analysis_status == "completed"
    assert current.ai_analysis["weighted_score"] == 8
    assert current.ai_analysis["source"] == "corrected_transcript"
    assert current.ai_analysis_version == 5


def test_recovery_resumes_interrupted_worker_with_the_latest_corrected_transcript(
    db, analysis_interview, monkeypatch,
):
    corrected_text = "我负责工厂整体安全体系。"
    analysis_interview.transcripts = {
        **analysis_interview.transcripts,
        "corrected_full_interview_data": {
            "text": corrected_text,
            "segments": [{"start": 0, "end": 1, "text": corrected_text}],
        },
    }
    analysis_interview.ai_analysis_status = "analyzing"
    analysis_interview.ai_analysis_started_at = service.utcnow()
    db.commit()
    inputs = []

    def generate(prompt, **kwargs):
        inputs.append(json.loads(prompt)["text"])
        return analysis_response(inputs[-1])

    monkeypatch.setattr(service, "generate_text", generate)
    monitor.resume_asr_jobs_for_tenant(analysis_interview.tenant_id)
    db.expire_all()
    current = db.get(Interview, analysis_interview.id)
    assert inputs == [corrected_text]
    assert current.ai_analysis_status == "completed"
    assert current.ai_analysis["source"] == "corrected_transcript"


def test_same_transcript_retry_also_invalidates_an_active_result(
    db, analysis_interview, monkeypatch,
):
    tenant_id, interview_id = analysis_interview.tenant_id, analysis_interview.id

    def generate(prompt, **kwargs):
        with Session(db.get_bind()) as request_db:
            current = request_db.get(Interview, interview_id)
            current.ai_analysis_status = "pending"
            request_db.commit()
        return analysis_response(json.loads(prompt)["text"], 3.8)

    monkeypatch.setattr(service, "generate_text", generate)
    service.analyze_sealed_recording(tenant_id, interview_id)
    db.expire_all()
    current = db.get(Interview, interview_id)
    assert current.ai_analysis_status == "pending"
    assert current.ai_analysis is None
    assert current.ai_analysis_version == 0
