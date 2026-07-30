"""Periodic recovery and retention work for interview recording lifecycles."""

from __future__ import annotations

import logging
import os
import re
import threading
from datetime import timedelta
from uuid import UUID

from app.config.database import SessionLocal
from app.config.tenant_session import tenant_session
from app.models.file_models import StoredFile
from app.models.models import Interview
from app.models.tenant_models import Tenant, TenantStatus
from app.services.interview_lifecycle_service import (
    as_utc,
    process_asr_job,
    seal_recording,
    utcnow,
)
from app.utils.file_storage import stage_file_deletions, unlink_file_locations


logger = logging.getLogger(__name__)
_monitor_started = False
_monitor_lock = threading.Lock()
_FILE_URL = re.compile(r"^/api/files/([0-9a-fA-F-]{36})$")


def _active_tenant_ids() -> list[UUID]:
    db = SessionLocal()
    try:
        return [value for (value,) in db.query(Tenant.id).filter(Tenant.status == TenantStatus.ACTIVE).all()]
    finally:
        db.close()


def recover_stale_recordings_for_tenant(tenant_id: UUID) -> list[UUID]:
    analysis_ids: list[UUID] = []
    cutoff = utcnow() - timedelta(minutes=30)
    with tenant_session(tenant_id) as db:
        interviews = db.query(Interview).filter(
            Interview.lifecycle_state == "in_progress",
            Interview.recording_state == "recording",
        ).all()
        for interview in interviews:
            if not interview.recording_heartbeat_at or as_utc(interview.recording_heartbeat_at) > cutoff:
                continue
            interview.lifecycle_state = "ending"
            interview.recording_state = "ending"
            interview.end_reason = "recording_disconnected_timeout"
            db.commit()
            if interview.recording_chunks:
                sealed = seal_recording(
                    db,
                    interview.id,
                    interview.recording_session_id,
                    None,
                )
                analysis_ids.append(sealed.id)
            else:
                interview.lifecycle_state = "ended"
                interview.recording_state = "failed"
                interview.ended_at = utcnow()
                interview.ai_analysis_status = "failed"
                interview.ai_analysis_error = "Recording disconnected before any audio was uploaded"
                db.commit()
    return analysis_ids


def purge_expired_recordings_for_tenant(tenant_id: UUID) -> int:
    purged = 0
    with tenant_session(tenant_id) as db:
        interviews = db.query(Interview).filter(
            Interview.recording_delete_after.isnot(None),
            Interview.recording_delete_after <= utcnow(),
        ).all()
        for interview in interviews:
            url = (interview.audio_records or {}).get("full_interview")
            match = _FILE_URL.fullmatch(url or "")
            if match:
                record = db.query(StoredFile).filter(StoredFile.id == UUID(match.group(1))).first()
                if record:
                    locations = stage_file_deletions(db, [record])
                    values = dict(interview.audio_records or {})
                    values.pop("full_interview", None)
                    interview.audio_records = values
                    interview.recording_delete_after = None
                    db.commit()
                    unlink_file_locations(locations)
                    purged += 1
                    continue
            interview.recording_delete_after = None
            db.commit()
    return purged


def resume_asr_jobs_for_tenant(tenant_id: UUID) -> int:
    resumed = 0
    with tenant_session(tenant_id) as db:
        interviews = db.query(Interview).filter(Interview.lifecycle_state == "ended").all()
        candidates = [
            interview.id
            for interview in interviews
            if (interview.audio_records or {}).get("full_interview")
            and (
                interview.asr_job_delete_pending
                or interview.asr_job_status in {"pending", "submitting", "queued", "processing", "retry_wait"}
                or (
                    interview.asr_job_status == "completed"
                    and interview.ai_analysis_status in {"pending", "transcribing", "analyzing"}
                )
            )
            and (
                interview.asr_job_delete_pending
                or not interview.asr_job_next_poll_at
                or as_utc(interview.asr_job_next_poll_at) <= utcnow()
            )
        ]
    for interview_id in candidates:
        process_asr_job(tenant_id, interview_id)
        resumed += 1
    return resumed


def run_lifecycle_maintenance_once() -> None:
    for tenant_id in _active_tenant_ids():
        try:
            for interview_id in recover_stale_recordings_for_tenant(tenant_id):
                process_asr_job(tenant_id, interview_id)
            resume_asr_jobs_for_tenant(tenant_id)
            purge_expired_recordings_for_tenant(tenant_id)
        except Exception as error:
            logger.error(
                "Interview lifecycle maintenance failed (%s)",
                type(error).__name__,
                extra={"tenant_id": str(tenant_id)},
            )


def _monitor_loop() -> None:
    interval = int(os.getenv("INTERVIEW_LIFECYCLE_MONITOR_SECONDS", "60"))
    while True:
        run_lifecycle_maintenance_once()
        threading.Event().wait(max(15, interval))


def start_interview_lifecycle_monitor() -> None:
    global _monitor_started
    if os.getenv("APP_ENV") == "test":
        return
    with _monitor_lock:
        if _monitor_started:
            return
        threading.Thread(target=_monitor_loop, name="interview-lifecycle-monitor", daemon=True).start()
        _monitor_started = True
