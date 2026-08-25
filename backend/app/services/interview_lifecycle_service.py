"""Deep module for interview, recording, AI, review, and decision lifecycles."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import SpooledTemporaryFile
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config.tenant_session import tenant_session
from app.core.observability import background_task_context
from app.models.file_models import StoredFile
from app.models.models import (
    Interview,
    InterviewPanel,
    InterviewResult,
    InterviewStatus,
    Position,
    User,
    UserRole,
)
from app.services.resume_interview_status import (
    apply_final_decision,
    mark_interview_ended,
    mark_interview_started,
)
from app.services.interview_timing import require_interview_start_time
from app.services.audio_service import (
    AsrServiceError,
    create_transcription_job,
    delete_transcription_job,
    get_transcription_config,
    get_transcription_job,
    transcribe_audio,
)
from app.services.ai_service import generate_text
from app.utils.prompt_manager import prompt_manager
from app.utils.file_storage import (
    MAX_UPLOAD_SIZE,
    UPLOAD_ROOT,
    cleanup_new_file,
    save_upload_file,
    stage_file_deletions,
    stored_file_path,
    unlink_file_locations,
)


RECORDING_RESERVATION_SECONDS = 60
RECORDING_DISCONNECT_SECONDS = 30
RECORDING_RETENTION_DAYS = 30
REMINDER_COOLDOWN_HOURS = 24
MAX_RECORDING_SIZE = max(MAX_UPLOAD_SIZE, 2 * 1024 * 1024 * 1024)
MAX_RECORDING_CHUNKS = 10_000
MAX_REALTIME_TRANSCRIPT_SEGMENTS = 10_000
ASR_MAX_ATTEMPTS = 3
ASR_POLL_SECONDS = 15

SCORE_DIMENSIONS = {
    "technical_fit": {"label": "技术匹配", "weight": 35, "gate": True},
    "problem_solving": {"label": "问题解决", "weight": 20, "gate": True},
    "learning_ability": {"label": "学习能力", "weight": 15, "gate": False},
    "engineering_mindset": {"label": "工程化思维", "weight": 15, "gate": True},
    "collaboration": {"label": "协作能力", "weight": 10, "gate": False},
    "culture_fit": {"label": "文化匹配", "weight": 5, "gate": False},
}
FINAL_DECISIONS = {
    "next_round": InterviewResult.NEXT_ROUND,
    "passed": InterviewResult.PASSED,
    "rejected": InterviewResult.REJECTED,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def remux_seekable_webm(path: Path) -> None:
    """Rewrite a MediaRecorder WebM with duration/cues so browsers can seek it."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required to finalize interview recordings")
    output = path.with_name(f"{path.stem}.seekable{path.suffix}")
    try:
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-i", str(path),
                "-map", "0:a:0",
                "-c:a", "copy",
                "-map_metadata", "-1",
                str(output),
            ],
            check=True,
            capture_output=True,
            timeout=600,
        )
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError("ffmpeg produced an empty interview recording")
        output.replace(path)
    finally:
        output.unlink(missing_ok=True)


def _role_value(user: User) -> str:
    return getattr(user.role, "value", user.role)


def _locked_interview(db: Session, interview_id: UUID) -> Interview:
    interview = (
        db.query(Interview)
        .filter(Interview.id == interview_id)
        .with_for_update()
        .first()
    )
    if interview is None:
        raise HTTPException(status_code=404, detail="Interview not found")
    return interview


def _require_owner(interview: Interview, user: User, session_id: UUID) -> None:
    if interview.recording_session_id != session_id or interview.recording_owner_id != user.id:
        raise HTTPException(status_code=409, detail="Recording session is owned by another interviewer")


def reserve_recording(db: Session, interview_id: UUID, user: User) -> Interview:
    interview = _locked_interview(db, interview_id)
    if interview.lifecycle_state not in {"scheduled", "in_progress"}:
        raise HTTPException(status_code=409, detail="Interview cannot start recording in its current state")
    if interview.lifecycle_state == "scheduled":
        require_interview_start_time(interview)

    now = utcnow()
    live_reservation = (
        interview.recording_state == "reserved"
        and interview.recording_reservation_expires_at
        and as_utc(interview.recording_reservation_expires_at) > now
    )
    live_recording = (
        interview.recording_state == "recording"
        and interview.recording_heartbeat_at
        and as_utc(interview.recording_heartbeat_at) > now - timedelta(seconds=RECORDING_DISCONNECT_SECONDS)
    )
    if (live_reservation or live_recording) and interview.recording_owner_id != user.id:
        raise HTTPException(status_code=409, detail="Another interviewer owns the recording")

    if interview.recording_owner_id == user.id and (live_reservation or live_recording):
        return interview

    is_new_interview = interview.lifecycle_state == "scheduled"
    interview.recording_session_id = uuid4()
    interview.recording_owner_id = user.id
    interview.recording_state = "reserved"
    interview.recording_reservation_expires_at = now + timedelta(seconds=RECORDING_RESERVATION_SECONDS)
    interview.recording_heartbeat_at = now
    if is_new_interview:
        interview.recording_chunks = []
        interview.ai_analysis_status = "pending"
        interview.ai_analysis_error = None
        interview.asr_job_id = None
        interview.asr_job_status = "pending"
        interview.asr_job_attempts = 0
        interview.asr_job_next_poll_at = utcnow()
        interview.asr_job_history = []
        interview.asr_job_delete_pending = False
    db.commit()
    db.refresh(interview)
    return interview


def confirm_recording(db: Session, interview_id: UUID, session_id: UUID, user: User) -> Interview:
    interview = _locked_interview(db, interview_id)
    _require_owner(interview, user, session_id)
    if interview.lifecycle_state == "scheduled":
        require_interview_start_time(interview)
    now = utcnow()
    if interview.recording_state == "recording":
        return interview
    if interview.recording_state != "reserved" or not interview.recording_reservation_expires_at or as_utc(interview.recording_reservation_expires_at) <= now:
        raise HTTPException(status_code=409, detail="Recording reservation expired")

    interview.recording_state = "recording"
    interview.lifecycle_state = "in_progress"
    interview.recording_heartbeat_at = now
    interview.started_at = interview.started_at or now
    interview.status = InterviewStatus.IN_PROGRESS
    mark_interview_started(interview)
    db.commit()
    db.refresh(interview)
    return interview


def heartbeat_recording(db: Session, interview_id: UUID, session_id: UUID, user: User) -> Interview:
    interview = _locked_interview(db, interview_id)
    _require_owner(interview, user, session_id)
    if interview.recording_state not in {"recording", "ending"}:
        raise HTTPException(status_code=409, detail="Recording is not active")
    interview.recording_heartbeat_at = utcnow()
    db.commit()
    return interview


def persist_realtime_transcript(
    db: Session,
    interview_id: UUID,
    session_id: UUID,
    segments: list[dict],
    user: User,
) -> dict:
    """Persist finalized realtime segments without replacing the offline transcript."""
    interview = _locked_interview(db, interview_id)
    _require_owner(interview, user, session_id)
    if interview.recording_state not in {"recording", "ending"}:
        raise HTTPException(status_code=409, detail="Recording is not accepting realtime transcripts")

    transcripts = dict(interview.transcripts or {})
    realtime_data = transcripts.get("realtime_full_interview_data")
    existing = (
        list(realtime_data.get("segments") or [])
        if isinstance(realtime_data, dict)
        else []
    )
    known_ids = {
        str(item.get("id"))
        for item in existing
        if isinstance(item, dict) and item.get("id")
    }
    accepted = []
    for segment in segments:
        segment_id = str(segment["id"])
        if segment_id in known_ids:
            continue
        accepted.append(segment)
        known_ids.add(segment_id)

    if len(existing) + len(accepted) > MAX_REALTIME_TRANSCRIPT_SEGMENTS:
        raise HTTPException(status_code=413, detail="Realtime transcript has too many segments")

    combined = existing + accepted
    text = "\n".join(
        str(item.get("text") or "").strip()
        for item in combined
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    )
    transcripts["realtime_full_interview"] = text
    transcripts["realtime_full_interview_data"] = {
        "text": text,
        "segments": combined,
        "source": "realtime",
        "updated_at": utcnow().isoformat(),
    }
    interview.transcripts = transcripts
    db.commit()
    return {"accepted": len(accepted), "total": len(combined)}


def append_recording_chunk(
    db: Session,
    interview_id: UUID,
    session_id: UUID,
    chunk_index: int,
    stored: StoredFile,
    user: User,
) -> dict:
    try:
        interview = _locked_interview(db, interview_id)
        _require_owner(interview, user, session_id)
        if interview.recording_state not in {"recording", "ending"}:
            raise HTTPException(status_code=409, detail="Recording is not accepting chunks")
        chunks = list(interview.recording_chunks or [])
        for item in chunks:
            if item["index"] == chunk_index:
                if item["size"] == stored.size:
                    cleanup_new_file(db, stored)
                    return item
                raise HTTPException(
                    status_code=409,
                    detail="Recording chunk conflicts with an existing chunk",
                )
        if chunk_index != len(chunks):
            raise HTTPException(status_code=409, detail=f"Expected recording chunk {len(chunks)}")
        if len(chunks) >= MAX_RECORDING_CHUNKS:
            raise HTTPException(status_code=413, detail="Recording has too many chunks")
        try:
            accumulated_size = sum(int(item["size"]) for item in chunks)
        except (KeyError, TypeError, ValueError):
            raise HTTPException(
                status_code=409,
                detail="Recording chunk metadata is invalid",
            ) from None
        if accumulated_size + stored.size > MAX_RECORDING_SIZE:
            raise HTTPException(status_code=413, detail="Recording exceeds the maximum size")
        db.add(stored)
        item = {"index": chunk_index, "file_id": str(stored.id), "size": stored.size}
        chunks.append(item)
        interview.recording_chunks = chunks
        interview.recording_heartbeat_at = utcnow()
        db.commit()
        return item
    except Exception:
        cleanup_new_file(db, stored)
        raise


def begin_ending(
    db: Session,
    interview_id: UUID,
    session_id: UUID,
    user: User,
    reason: str | None = None,
) -> Interview:
    interview = _locked_interview(db, interview_id)
    is_admin = _role_value(user) in {UserRole.ADMIN.value, UserRole.HR.value}
    if not is_admin:
        _require_owner(interview, user, session_id)
    if interview.lifecycle_state == "ended":
        return interview
    if interview.recording_state not in {"recording", "ending"}:
        raise HTTPException(status_code=409, detail="Interview recording is not active")
    interview.lifecycle_state = "ending"
    interview.recording_state = "ending"
    interview.end_reason = reason
    db.commit()
    db.refresh(interview)
    return interview


def force_end_interview(
    db: Session,
    interview_id: UUID,
    user: User,
    reason: str,
) -> Interview:
    """End a stuck interview without requiring a live recording session."""
    if _role_value(user) not in {UserRole.ADMIN.value, UserRole.HR.value}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin or HR access required")

    interview = _locked_interview(db, interview_id)
    if interview.lifecycle_state == "ended" and not interview.recording_chunks:
        return interview
    if interview.lifecycle_state not in {"in_progress", "ending", "ended"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an interview in progress can be force-ended",
        )

    if interview.recording_chunks:
        interview.lifecycle_state = "ending"
        interview.recording_state = "ending"
        interview.end_reason = reason.strip()
        interview.ai_analysis_status = "pending"
        interview.ai_analysis_error = None
        interview.asr_job_id = None
        interview.asr_job_status = "pending"
        interview.asr_job_attempts = 0
        interview.asr_job_next_poll_at = utcnow()
        interview.asr_job_delete_pending = False
        db.commit()
        return seal_recording(
            db,
            interview.id,
            interview.recording_session_id or uuid4(),
            user,
        )

    now = utcnow()
    interview.lifecycle_state = "ended"
    interview.ended_at = now
    interview.notes_revealed_at = now
    interview.end_reason = reason.strip()
    interview.recording_state = "failed"
    interview.recording_reservation_expires_at = None
    interview.recording_heartbeat_at = None
    interview.ai_analysis_status = "failed"
    interview.ai_analysis_error = "Interview was force-ended without any recording chunks"
    interview.asr_job_status = "failed"
    interview.asr_job_next_poll_at = None
    interview.status = InterviewStatus.COMPLETED
    mark_interview_ended(interview)
    for panel in interview.panels or []:
        panel.notes_frozen_at = now
    db.commit()
    db.refresh(interview)
    return interview


def seal_recording(db: Session, interview_id: UUID, session_id: UUID, user: User | None) -> Interview:
    interview = _locked_interview(db, interview_id)
    is_admin = user is None or _role_value(user) in {UserRole.ADMIN.value, UserRole.HR.value}
    if not is_admin:
        _require_owner(interview, user, session_id)
    if interview.lifecycle_state == "ended" and (interview.audio_records or {}).get("full_interview"):
        return interview
    if interview.recording_state != "ending":
        raise HTTPException(status_code=409, detail="Interview must be ending before it can be sealed")

    chunks = sorted(interview.recording_chunks or [], key=lambda item: item["index"])
    if not chunks:
        raise HTTPException(status_code=409, detail="No recording chunks were uploaded")
    file_ids = [UUID(item["file_id"]) for item in chunks]
    records = db.query(StoredFile).filter(StoredFile.id.in_(file_ids)).all()
    by_id = {record.id: record for record in records}
    if any(file_id not in by_id for file_id in file_ids):
        raise HTTPException(status_code=409, detail="Recording chunks are incomplete")

    combined = SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    for file_id in file_ids:
        with stored_file_path(by_id[file_id]).open("rb") as source:
            while data := source.read(1024 * 1024):
                combined.write(data)
    combined.seek(0)
    upload = UploadFile(filename="full_interview.webm", file=combined)
    stored = None
    try:
        stored = save_upload_file(
            upload,
            interview.tenant_id,
            "interview_audio",
            resource_type="interview",
            resource_id=interview.id,
            max_size=MAX_RECORDING_SIZE,
        )
        remux_seekable_webm(stored_file_path(stored))
        stored.size = stored_file_path(stored).stat().st_size
        db.add(stored)
        locations = stage_file_deletions(db, records)
        interview.audio_records = {**(interview.audio_records or {}), "full_interview": f"/api/files/{stored.id}"}
        interview.recording_chunks = []
        interview.recording_state = "sealed"
        interview.lifecycle_state = "ended"
        interview.ended_at = utcnow()
        interview.notes_revealed_at = interview.ended_at
        interview.recording_delete_after = interview.ended_at + timedelta(days=RECORDING_RETENTION_DAYS)
        interview.ai_analysis_status = "pending"
        interview.status = InterviewStatus.ANALYZING
        mark_interview_ended(interview)
        for panel in interview.panels or []:
            panel.notes_frozen_at = interview.ended_at
        db.commit()
        unlink_file_locations(locations)
    except HTTPException:
        raise
    except Exception:
        if stored is not None:
            cleanup_new_file(db, stored)
        else:
            db.rollback()
        raise
    finally:
        combined.close()
    db.refresh(interview)
    return interview


class AnalysisContractError(ValueError):
    """Raised when the model does not return the configured analysis contract."""


def _extract_json(value: str) -> dict:
    match = re.search(r"\{.*\}", value or "", re.DOTALL)
    if not match:
        raise AnalysisContractError("AI 返回内容不是合法 JSON")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise AnalysisContractError("AI 返回的 JSON 格式错误") from error
    if not isinstance(parsed, dict):
        raise AnalysisContractError("AI 返回结果必须是 JSON 对象")
    return parsed


def _evidence_match_text(value: object) -> str:
    """Normalize harmless ASR/LLM punctuation differences for quote matching."""
    return "".join(
        character.casefold()
        for character in str(value or "")
        if not character.isspace()
        and not unicodedata.category(character).startswith("P")
    )


def _normalized_evidence(
    value: object,
    transcript_data: dict | None = None,
) -> dict | None:
    """Resolve one model quote to authoritative transcript segment timestamps."""
    if not isinstance(value, dict):
        return None
    quote = value.get("quote")
    if not isinstance(quote, str) or not quote.strip():
        return None

    start = value.get("start")
    end = value.get("end")
    claimed_range_valid = (
        isinstance(start, (int, float))
        and not isinstance(start, bool)
        and isinstance(end, (int, float))
        and not isinstance(end, bool)
        and start >= 0
        and end >= start
    )
    if transcript_data is None:
        if not claimed_range_valid:
            return None
        return {"start": float(start), "end": float(end), "quote": quote.strip()}

    normalized_quote = _evidence_match_text(quote)
    if not normalized_quote:
        return None
    indexed_segments = []
    transcript_text = ""
    for segment in transcript_data.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        segment_start = segment.get("start")
        segment_end = segment.get("end")
        if (
            not isinstance(segment_start, (int, float))
            or isinstance(segment_start, bool)
            or not isinstance(segment_end, (int, float))
            or isinstance(segment_end, bool)
            or segment_start < 0
            or segment_end < segment_start
        ):
            continue
        segment_text = _evidence_match_text(segment.get("text"))
        if not segment_text:
            continue
        text_start = len(transcript_text)
        transcript_text += segment_text
        indexed_segments.append({
            "text_start": text_start,
            "text_end": len(transcript_text),
            "start": float(segment_start),
            "end": float(segment_end),
        })

    candidates = []
    search_from = 0
    while True:
        match_start = transcript_text.find(normalized_quote, search_from)
        if match_start < 0:
            break
        match_end = match_start + len(normalized_quote)
        matched_segments = [
            segment
            for segment in indexed_segments
            if segment["text_end"] > match_start and segment["text_start"] < match_end
        ]
        if matched_segments:
            resolved_start = matched_segments[0]["start"]
            resolved_end = matched_segments[-1]["end"]
            distance = (
                abs(resolved_start - float(start)) + abs(resolved_end - float(end))
                if claimed_range_valid
                else resolved_start
            )
            candidates.append((distance, resolved_start, resolved_end))
        search_from = match_start + 1

    if not candidates:
        return None
    _, resolved_start, resolved_end = min(candidates, key=lambda item: item[0])
    return {
        "start": resolved_start,
        "end": resolved_end,
        "quote": quote.strip(),
    }


def _required_text(value: dict, key: str) -> str:
    text = value.get(key)
    if not isinstance(text, str) or not text.strip():
        raise AnalysisContractError(f"AI 返回结果缺少 {key}")
    return text.strip()


def _normalize_findings(value: dict, key: str, transcript_data: dict | None) -> list[dict]:
    findings = value.get(key)
    if not isinstance(findings, list) or len(findings) > 4:
        raise AnalysisContractError(f"{key} 必须是最多 4 条的数组")
    normalized = []
    for finding in findings:
        if not isinstance(finding, dict):
            raise AnalysisContractError(f"{key} 中的条目格式错误")
        evidence = _normalized_evidence(finding.get("evidence"), transcript_data)
        if evidence is None:
            continue
        normalized.append({
            "conclusion": _required_text(finding, "conclusion"),
            "evidence": evidence,
            "job_impact": _required_text(finding, "job_impact"),
        })
    return normalized


def enforce_analysis_contract(value: dict, transcript_data: dict | None = None) -> dict:
    if value.get("format_version") != 2:
        raise AnalysisContractError("AI 返回结果缺少 format_version 2")
    dimensions = value.get("dimensions")
    if not isinstance(dimensions, dict):
        raise AnalysisContractError("AI 返回结果缺少 dimensions")
    normalized = {}
    gate_missing = False
    gate_failed = False
    weighted_total = 0.0
    coverage = 0
    for key, config in SCORE_DIMENSIONS.items():
        item = dimensions.get(key)
        if not isinstance(item, dict):
            raise AnalysisContractError(f"AI 返回结果缺少评分维度 {key}")
        score = item.get("score")
        raw_evidence = item.get("evidence")
        if not isinstance(raw_evidence, list):
            raise AnalysisContractError(f"评分维度 {key} 的 evidence 必须是数组")
        evidence = [
            normalized_evidence
            for entry in raw_evidence
            if (normalized_evidence := _normalized_evidence(entry, transcript_data))
            is not None
        ]
        assessment = _required_text(item, "assessment")
        if score is None:
            evidence = []
        elif (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not 1 <= score <= 10
        ):
            raise AnalysisContractError(f"评分维度 {key} 的评分或证据无效")
        elif not evidence:
            score = None
        else:
            score = round(float(score), 1)
            coverage += config["weight"]
            weighted_total += score * config["weight"] / 100
        if config["gate"] and score is None:
            gate_missing = True
        if config["gate"] and score is not None and score < 6:
            gate_failed = True
        normalized[key] = {
            "score": score,
            "assessment": assessment,
            "evidence": evidence,
        }
    recommendation = value.get("recommendation")
    if recommendation not in {"next_round", "passed", "waitlist", "rejected", "inconclusive"}:
        raise AnalysisContractError("AI 返回的 recommendation 无效")
    if gate_missing:
        recommendation = "inconclusive"
    elif gate_failed and recommendation in {"next_round", "passed"}:
        recommendation = "waitlist"
    questions = value.get("next_round_questions")
    if (
        not isinstance(questions, list)
        or any(not isinstance(question, str) or not question.strip() for question in questions)
    ):
        raise AnalysisContractError("next_round_questions 必须是字符串数组")
    if recommendation == "inconclusive" and not questions:
        questions = ["请在下一轮围绕证据不足的关键维度补充具体案例和实现细节。"]
    return {
        "format_version": 2,
        "dimensions": normalized,
        "weighted_score": round(weighted_total, 1) if coverage else None,
        "coverage": coverage,
        "recommendation": recommendation,
        "summary": _required_text(value, "summary"),
        "strengths": _normalize_findings(value, "strengths", transcript_data),
        "risks": _normalize_findings(value, "risks", transcript_data),
        "recommendation_reason": _required_text(value, "recommendation_reason"),
        "next_round_questions": [question.strip() for question in questions],
    }


def _asr_history(interview: Interview, **values) -> None:
    history = list(interview.asr_job_history or [])
    history.append({"at": utcnow().isoformat(), **values})
    interview.asr_job_history = history


def _asr_retry_delay(attempts: int) -> timedelta:
    delays = (30, 120, 300)
    return timedelta(seconds=delays[min(max(attempts - 1, 0), len(delays) - 1)])


def _mark_asr_failure(interview: Interview, error: AsrServiceError | None = None) -> None:
    retryable = error is None or error.retryable
    if retryable and interview.asr_job_attempts < ASR_MAX_ATTEMPTS:
        interview.asr_job_status = "retry_wait"
        delay = (
            timedelta(seconds=error.retry_after)
            if error is not None and error.retry_after
            else _asr_retry_delay(interview.asr_job_attempts)
        )
        interview.asr_job_next_poll_at = utcnow() + delay
        interview.ai_analysis_status = "transcribing"
    else:
        interview.asr_job_status = "failed"
        interview.asr_job_next_poll_at = None
        interview.ai_analysis_status = "failed"
        interview.ai_analysis_error = "AsrTranscriptionFailed"


def _normalize_asr_result(payload: dict) -> dict:
    result = payload.get("result")
    if not isinstance(result, dict):
        raise AsrServiceError(retryable=False)
    text = result.get("text")
    raw_segments = result.get("segments")
    if not isinstance(text, str) or not isinstance(raw_segments, list):
        raise AsrServiceError(retryable=False)
    segments = []
    for segment in raw_segments:
        if not isinstance(segment, dict):
            continue
        segments.append({
            "speaker": segment.get("speaker") or "说话人",
            "text": segment.get("text") or "",
            "start": segment.get("start", 0),
            "end": segment.get("end", 0),
        })
    return {
        "text": text,
        "segments": segments,
        "language": result.get("language"),
        "duration": result.get("duration"),
        "model": result.get("model"),
    }


def _delete_remote_asr_job(interview: Interview, config: dict) -> None:
    if not interview.asr_job_id:
        interview.asr_job_delete_pending = False
        return
    job_id = interview.asr_job_id
    try:
        delete_transcription_job(job_id, config)
        interview.asr_job_delete_pending = False
        interview.asr_job_id = None
        _asr_history(interview, job_id=job_id, status="deleted")
    except AsrServiceError:
        interview.asr_job_delete_pending = True


@background_task_context
def process_asr_job(tenant_id: UUID, interview_id: UUID) -> None:
    """Advance one durable ASR job by one state transition."""
    should_analyze = False
    use_legacy_provider = False
    with tenant_session(tenant_id) as db:
        interview = (
            db.query(Interview)
            .filter(Interview.id == interview_id)
            .with_for_update()
            .first()
        )
        if (
            interview is None
            or interview.lifecycle_state != "ended"
            or not (interview.audio_records or {}).get("full_interview")
        ):
            return

        config = get_transcription_config(db)
        if config.get("provider") != "openai_compatible":
            use_legacy_provider = True
        elif interview.asr_job_delete_pending and interview.asr_job_id:
            _delete_remote_asr_job(interview, config)
            db.commit()

        if use_legacy_provider:
            pass
        elif interview.asr_job_status == "completed":
            should_analyze = interview.ai_analysis_status in {"pending", "transcribing", "analyzing"}
        elif interview.asr_job_status == "failed":
            return
        elif (
            interview.asr_job_next_poll_at
            and as_utc(interview.asr_job_next_poll_at) > utcnow()
        ):
            return
        elif not interview.asr_job_id:
            interview.asr_job_attempts = (interview.asr_job_attempts or 0) + 1
            interview.asr_job_status = "submitting"
            interview.ai_analysis_status = "transcribing"
            interview.ai_analysis_started_at = interview.ai_analysis_started_at or utcnow()
            db.commit()
            url = (interview.audio_records or {}).get("full_interview")
            match = re.fullmatch(r"/api/files/([0-9a-fA-F-]{36})", url or "")
            stored = db.query(StoredFile).filter(StoredFile.id == UUID(match.group(1))).first() if match else None
            if stored is None:
                interview.asr_job_status = "failed"
                interview.ai_analysis_status = "failed"
                interview.ai_analysis_error = "Recording file is missing"
                db.commit()
                return
            try:
                payload = create_transcription_job(str(stored_file_path(stored)), config)
                interview.asr_job_id = str(payload["id"])
                interview.asr_job_status = str(payload.get("status") or "queued")
                interview.asr_job_next_poll_at = utcnow() + timedelta(seconds=ASR_POLL_SECONDS)
                interview.ai_analysis_error = None
                _asr_history(
                    interview,
                    attempt=interview.asr_job_attempts,
                    job_id=interview.asr_job_id,
                    status=interview.asr_job_status,
                )
            except AsrServiceError as error:
                _asr_history(
                    interview,
                    attempt=interview.asr_job_attempts,
                    status="submission_failed",
                    provider_status=error.status_code,
                )
                _mark_asr_failure(interview, error)
            db.commit()
        else:
            try:
                payload = get_transcription_job(interview.asr_job_id, config)
                remote_status = str(payload.get("status") or "processing")
                interview.asr_job_status = remote_status
                if remote_status == "completed":
                    transcript_data = _normalize_asr_result(payload)
                    interview.transcripts = {
                        **(interview.transcripts or {}),
                        "full_interview": transcript_data["text"],
                        "full_interview_data": transcript_data,
                    }
                    interview.asr_job_status = "completed"
                    interview.asr_job_next_poll_at = None
                    interview.asr_job_delete_pending = True
                    interview.ai_analysis_status = "analyzing"
                    interview.ai_analysis_error = None
                    _asr_history(interview, job_id=interview.asr_job_id, status="completed")
                    db.commit()
                    _delete_remote_asr_job(interview, config)
                    db.commit()
                    should_analyze = True
                elif remote_status in {"failed", "cancelled"}:
                    _asr_history(interview, job_id=interview.asr_job_id, status=remote_status)
                    interview.asr_job_delete_pending = True
                    _delete_remote_asr_job(interview, config)
                    _mark_asr_failure(interview)
                    db.commit()
                else:
                    interview.asr_job_next_poll_at = utcnow() + timedelta(seconds=ASR_POLL_SECONDS)
                    db.commit()
            except AsrServiceError as error:
                if error.retryable:
                    interview.asr_job_next_poll_at = utcnow() + timedelta(
                        seconds=error.retry_after or ASR_POLL_SECONDS
                    )
                else:
                    _mark_asr_failure(interview, error)
                db.commit()

    if use_legacy_provider or should_analyze:
        analyze_sealed_recording(tenant_id, interview_id)


@background_task_context
def analyze_sealed_recording(tenant_id: UUID, interview_id: UUID, use_corrected: bool = False) -> None:
    with tenant_session(tenant_id) as db:
        interview = db.query(Interview).filter(Interview.id == interview_id).first()
        if not interview:
            return
        url = (interview.audio_records or {}).get("full_interview")
        match = re.fullmatch(r"/api/files/([0-9a-fA-F-]{36})", url or "")
        if not match:
            interview.ai_analysis_status = "failed"
            interview.ai_analysis_error = "Recording file is missing"
            db.commit()
            return
        stored = db.query(StoredFile).filter(StoredFile.id == UUID(match.group(1))).first()
        if not stored:
            interview.ai_analysis_status = "failed"
            interview.ai_analysis_error = "Recording file is missing"
            db.commit()
            return

        interview.ai_analysis_status = "transcribing"
        interview.ai_analysis_started_at = utcnow()
        interview.ai_analysis_error = None
        db.commit()
        try:
            transcripts = interview.transcripts or {}
            corrected_data = transcripts.get("corrected_full_interview_data")
            completed_data = transcripts.get("full_interview_data")
            if use_corrected and corrected_data:
                transcript_data = corrected_data
            elif interview.asr_job_status == "completed" and completed_data:
                transcript_data = completed_data
            else:
                transcript_data = transcribe_audio(
                    str(stored_file_path(stored)),
                    config=get_transcription_config(db),
                )
            if (
                not isinstance(transcript_data, dict)
                or not isinstance(transcript_data.get("segments"), list)
                or not transcript_data["segments"]
            ):
                raise AnalysisContractError("录音转写缺少带时间戳的有效分段")
            transcript = transcript_data.get("text", "") if isinstance(transcript_data, dict) else str(transcript_data)
            transcript_values = dict(interview.transcripts or {})
            if use_corrected and corrected_data:
                transcript_values["analysis_transcript_data"] = transcript_data
            else:
                transcript_values["full_interview"] = transcript
                transcript_values["full_interview_data"] = transcript_data
            interview.transcripts = transcript_values
            interview.ai_analysis_status = "analyzing"
            db.commit()

            position = db.query(Position).filter(Position.id == interview.position_id).first()
            position_description = "\n\n".join(filter(None, [
                position.description if position else "",
                f"任职要求：\n{position.requirements}" if position and position.requirements else "",
            ]))
            prompt = prompt_manager.get_prompt(
                "generate_interview_evaluation",
                db=db,
                position_title=position.title if position else "未知岗位",
                position_description=position_description or "未提供岗位描述",
                score_dimensions=json.dumps(SCORE_DIMENSIONS, ensure_ascii=False),
                transcript_data=json.dumps(transcript_data, ensure_ascii=False),
            )
            if prompt["user"] in {"", "提示词变量缺失", "提示词格式化失败"}:
                raise AnalysisContractError("面试评价提示词配置无效")
            raw = generate_text(
                prompt["user"],
                db=db,
                system_prompt=prompt["system"],
                json_response=True,
            )
            analysis = enforce_analysis_contract(_extract_json(raw), transcript_data)
            analysis["matrix"] = SCORE_DIMENSIONS
            analysis["source"] = "corrected_transcript" if use_corrected and corrected_data else "recording_only"
            interview.ai_analysis = analysis
            interview.ai_analysis_status = "completed"
            interview.ai_analysis_error = None
            interview.ai_analysis_version = (interview.ai_analysis_version or 0) + 1
            interview.ai_analysis_completed_at = utcnow()
            interview.status = InterviewStatus.COMPLETED
            db.commit()
        except Exception as error:
            db.rollback()
            interview = db.query(Interview).filter(Interview.id == interview_id).first()
            if interview:
                interview.ai_analysis_status = "failed"
                interview.ai_analysis_error = (
                    str(error)
                    if isinstance(error, AnalysisContractError)
                    else "AI 分析服务异常，请稍后重试"
                )
                interview.status = InterviewStatus.COMPLETED
                db.commit()


def panel_for_user(db: Session, interview: Interview, user: User) -> InterviewPanel:
    panel = db.query(InterviewPanel).filter(
        InterviewPanel.interview_id == interview.id,
        InterviewPanel.interviewer_id == user.id,
    ).first()
    if panel is None:
        raise HTTPException(status_code=403, detail="Interview assignment required")
    return panel


def save_live_notes(db: Session, interview: Interview, user: User, notes: str) -> InterviewPanel:
    if interview.lifecycle_state != "in_progress":
        raise HTTPException(status_code=409, detail="Live notes can only be edited during the interview")
    panel = panel_for_user(db, interview, user)
    panel.live_notes = notes
    db.commit()
    db.refresh(panel)
    return panel


def add_note_supplement(db: Session, interview: Interview, user: User, content: str) -> InterviewPanel:
    if interview.lifecycle_state != "ended":
        raise HTTPException(status_code=409, detail="Supplements can only be added after the interview")
    panel = panel_for_user(db, interview, user)
    items = list(panel.note_supplements or [])
    items.append({"content": content, "author_id": str(user.id), "created_at": utcnow().isoformat()})
    panel.note_supplements = items
    db.commit()
    db.refresh(panel)
    return panel


def submit_human_review(
    db: Session,
    interview: Interview,
    user: User,
    scores: dict,
    comments: str,
    recommendation: str,
) -> InterviewPanel:
    if interview.lifecycle_state != "ended" or interview.final_decision_at is not None:
        raise HTTPException(status_code=409, detail="Human review is not editable")
    if scores and set(scores) != set(SCORE_DIMENSIONS):
        raise HTTPException(status_code=422, detail="All score dimensions are required")
    if any(not isinstance(value, int) or value < 1 or value > 10 for value in scores.values()):
        raise HTTPException(status_code=422, detail="Scores must be integers from 1 to 10")
    panel = panel_for_user(db, interview, user)
    now = utcnow()
    panel.human_scores = scores
    panel.human_comments = comments
    panel.human_recommendation = recommendation
    panel.human_review_submitted_at = panel.human_review_submitted_at or now
    panel.human_review_updated_at = now
    db.commit()
    db.refresh(panel)
    return panel


def confirm_final_decision(db: Session, interview: Interview, user: User, decision: str) -> Interview:
    if _role_value(user) not in {UserRole.ADMIN.value, UserRole.HR.value}:
        raise HTTPException(status_code=403, detail="HR or admin role required")
    if decision not in FINAL_DECISIONS:
        raise HTTPException(status_code=422, detail="Invalid final decision")
    if interview.final_decision_at is not None:
        raise HTTPException(status_code=409, detail="Final decision is locked")
    panels = {str(panel.interviewer_id): panel for panel in (interview.panels or [])}
    required_ids = [str(value) for value in (interview.panel_members or [])]
    missing = [value for value in required_ids if value not in panels or panels[value].human_review_submitted_at is None]
    if missing:
        raise HTTPException(status_code=409, detail={"message": "All assigned interviewers must submit", "missing": missing})
    interview.result = FINAL_DECISIONS[decision]
    interview.final_decision_by = user.id
    interview.final_decision_at = utcnow()
    interview.decision_history = [
        *(interview.decision_history or []),
        {
            "action": "confirmed",
            "result": decision,
            "actor_id": str(user.id),
            "at": interview.final_decision_at.isoformat(),
        },
    ]
    apply_final_decision(interview)
    db.commit()
    db.refresh(interview)
    return interview


def correct_final_decision(
    db: Session,
    interview: Interview,
    user: User,
    decision: str,
    reason: str,
) -> Interview:
    if _role_value(user) != UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="Admin role required")
    if interview.final_decision_at is None:
        raise HTTPException(status_code=409, detail="No final decision to correct")
    if decision not in FINAL_DECISIONS:
        raise HTTPException(status_code=422, detail="Invalid final decision")
    cleaned_reason = (reason or "").strip()
    if not cleaned_reason or len(cleaned_reason) > 500:
        raise HTTPException(status_code=422, detail="Correction reason must be 1-500 characters")

    previous = interview.result.value
    interview.result = FINAL_DECISIONS[decision]
    interview.final_decision_by = user.id
    interview.final_decision_at = utcnow()
    interview.decision_history = [
        *(interview.decision_history or []),
        {
            "action": "corrected",
            "from": previous,
            "to": decision,
            "reason": cleaned_reason,
            "actor_id": str(user.id),
            "at": interview.final_decision_at.isoformat(),
        },
    ]
    apply_final_decision(interview)
    db.commit()
    db.refresh(interview)
    return interview


def replace_reviewer(
    db: Session,
    interview: Interview,
    user: User,
    old_interviewer_id: UUID,
    new_interviewer_id: UUID,
) -> Interview:
    if _role_value(user) not in {UserRole.ADMIN.value, UserRole.HR.value}:
        raise HTTPException(status_code=403, detail="HR or admin role required")
    if interview.lifecycle_state != "ended" or interview.final_decision_at is not None:
        raise HTTPException(status_code=409, detail="Reviewers can only be replaced before the final decision")
    required = [str(value) for value in (interview.panel_members or [])]
    old_value = str(old_interviewer_id)
    new_value = str(new_interviewer_id)
    if old_value not in required:
        raise HTTPException(status_code=404, detail="Reviewer is not assigned")
    if new_value in required:
        raise HTTPException(status_code=409, detail="Replacement reviewer is already assigned")
    replacement = db.query(User).filter(User.id == new_interviewer_id, User.is_active == True).first()
    if replacement is None:
        raise HTTPException(status_code=404, detail="Replacement reviewer not found")
    required[required.index(old_value)] = new_value
    interview.panel_members = required
    existing = db.query(InterviewPanel).filter(
        InterviewPanel.interview_id == interview.id,
        InterviewPanel.interviewer_id == new_interviewer_id,
    ).first()
    if existing is None:
        db.add(InterviewPanel(
            tenant_id=interview.tenant_id,
            interview_id=interview.id,
            interviewer_id=new_interviewer_id,
            is_submitted=False,
        ))
    db.commit()
    db.refresh(interview)
    return interview


def update_reviewers(
    db: Session,
    interview: Interview,
    user: User,
    interviewer_ids: list[UUID],
) -> Interview:
    """Update the required human reviewers without changing the historic schedule."""
    if _role_value(user) not in {UserRole.ADMIN.value, UserRole.HR.value}:
        raise HTTPException(status_code=403, detail="HR or admin role required")
    if interview.lifecycle_state != "ended" or interview.final_decision_at is not None:
        raise HTTPException(status_code=409, detail="面试官只能在面试结束后、最终结果确认前调整")

    assignable_roles = [UserRole.ADMIN, UserRole.HR, UserRole.INTERVIEWER]
    users = db.query(User).filter(
        User.id.in_(interviewer_ids),
        User.is_active == True,
        User.role.in_(assignable_roles),
    ).all()
    users_by_id = {candidate.id: candidate for candidate in users}
    if any(interviewer_id not in users_by_id for interviewer_id in interviewer_ids):
        raise HTTPException(status_code=422, detail="面试官不存在、已停用或不可分配")

    existing_ids = {
        panel.interviewer_id
        for panel in db.query(InterviewPanel).filter(
            InterviewPanel.interview_id == interview.id,
        ).all()
    }
    for interviewer_id in set(interviewer_ids) - existing_ids:
        db.add(InterviewPanel(
            tenant_id=interview.tenant_id,
            interview_id=interview.id,
            interviewer_id=interviewer_id,
            is_submitted=False,
        ))

    # Removed reviewers are no longer required or authorized, while their frozen
    # notes/reviews remain as historical evidence instead of being destroyed.
    interview.panel_members = [str(interviewer_id) for interviewer_id in interviewer_ids]
    interview.interviewer = "面试小组"
    db.commit()
    db.refresh(interview)
    return interview
