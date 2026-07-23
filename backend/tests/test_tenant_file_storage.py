import os
import re
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient

from app.config.database import get_unscoped_db
from app.config.tenant_session import TenantSession
from app.core.tenant_dependencies import get_current_user_dep, get_tenant_db
from app.models.file_models import StoredFile
from app.models.models import InterviewPanel, Resume, User, UserRole
from app.models.tenant_models import PublicAccessToken, TenantDomain
from app.routes import files
from app.services.public_token_service import hash_token
from app.utils.file_storage import (
    MAX_UPLOAD_SIZE,
    delete_object_file,
    resolve_object_path,
    save_upload_file,
    commit_file_replacement,
    tenant_files_from_urls,
)


def _upload(name="candidate.pdf", content=b"resume", content_type="application/pdf"):
    return UploadFile(filename=name, file=BytesIO(content), headers={"content-type": content_type})


def _app(db, tenant, root, *, current_user=None):
    app = FastAPI()
    app.include_router(files.router, prefix="/api")
    app.include_router(files.public_router, prefix="/api")
    app.dependency_overrides[get_tenant_db] = lambda: db
    app.dependency_overrides[get_unscoped_db] = lambda: db
    user = current_user or SimpleNamespace(
        id=uuid4(), tenant_id=tenant.id, role=UserRole.HR
    )
    app.dependency_overrides[get_current_user_dep] = lambda: user
    files.UPLOAD_ROOT = root
    return app


def _bind_resume_file(db, tenant_id, stored):
    resume_id = stored.resource_id or uuid4()
    stored.resource_type = "resume"
    stored.resource_id = resume_id
    resume = Resume(
        id=resume_id,
        tenant_id=tenant_id,
        candidate_name="Candidate",
        file_id=stored.id,
    )
    db.add_all([stored, resume])
    return resume


def test_upload_uses_opaque_tenant_key_and_preserves_metadata(tmp_path, tenant_a):
    stored = save_upload_file(_upload("Jane Doe.PDF"), tenant_a.id, "resumes", root=tmp_path)
    parts = Path(stored.object_key).parts
    assert parts[:2] == (str(tenant_a.id), "resumes")
    assert "Jane Doe" not in stored.object_key
    assert stored.original_filename == "Jane Doe.PDF"
    assert stored.size == 6
    assert resolve_object_path(tmp_path, tenant_a.id, stored.object_key).read_bytes() == b"resume"


@pytest.mark.parametrize("category", ["../resumes", "a/b", "a\\b", ".", "", "/tmp"])
def test_upload_rejects_invalid_category(tmp_path, tenant_a, category):
    with pytest.raises(ValueError):
        save_upload_file(_upload(), tenant_a.id, category, root=tmp_path)


@pytest.mark.parametrize(
    "key", ["../../secret", "/tmp/secret", "other/resumes/a.pdf", "C:\\secret.pdf", "PLACEHOLDER/resumes/a/b.pdf"]
)
def test_resolve_rejects_escape_absolute_and_wrong_tenant(tmp_path, tenant_a, key):
    key = key.replace("PLACEHOLDER", str(tenant_a.id))
    with pytest.raises(ValueError):
        resolve_object_path(tmp_path, tenant_a.id, key)


def test_resolve_rejects_symlink_escape(tmp_path, tenant_a):
    tenant_root = tmp_path / str(tenant_a.id)
    tenant_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (tenant_root / "resumes").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(ValueError):
        resolve_object_path(tmp_path, tenant_a.id, f"{tenant_a.id}/resumes/file.pdf")


def test_upload_rejects_empty_and_oversized_and_cleans_partial(tmp_path, tenant_a):
    with pytest.raises(ValueError, match="empty"):
        save_upload_file(_upload(content=b""), tenant_a.id, "resumes", root=tmp_path)
    with pytest.raises(ValueError, match="large"):
        save_upload_file(
            _upload(content=b"x" * (MAX_UPLOAD_SIZE + 1)), tenant_a.id, "resumes", root=tmp_path
        )
    assert not list(tmp_path.rglob("*.part"))


def test_authenticated_download_is_tenant_scoped_and_has_safe_headers(
    db, tenant_a, tenant_b, tmp_path
):
    own = save_upload_file(_upload("safe\r\nX-Evil: yes.pdf", b"own"), tenant_a.id, "resumes", root=tmp_path)
    foreign = save_upload_file(_upload("other.pdf", b"foreign"), tenant_b.id, "resumes", root=tmp_path)
    _bind_resume_file(db, tenant_a.id, own)
    _bind_resume_file(db, tenant_b.id, foreign)
    db.commit()
    with TestClient(_app(db, tenant_a, tmp_path)) as client:
        response = client.get(f"/api/files/{own.id}")
        denied = client.get(f"/api/files/{foreign.id}")
    assert response.status_code == 200
    assert response.content == b"own"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert "\r" not in response.headers["content-disposition"]
    assert "\n" not in response.headers["content-disposition"]
    assert denied.status_code == 404


def test_public_download_requires_valid_token_and_matching_host(
    db, tenant_a, tenant_b, tmp_path
):
    stored = save_upload_file(_upload(content=b"public"), tenant_a.id, "resumes", root=tmp_path)
    db.add(stored)
    db.flush()
    raw = "a" * 43
    db.add(
        PublicAccessToken(
            token_hash=hash_token(raw), tenant_id=tenant_a.id,
            resource_type="stored_file", resource_id=stored.id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
    )
    db.add_all([
        TenantDomain(tenant_id=tenant_a.id, domain="a.example.test", is_primary=True),
        TenantDomain(tenant_id=tenant_b.id, domain="b.example.test", is_primary=True),
    ])
    db.commit()
    tenant_id = tenant_a.id
    stored_id = stored.id
    db.expunge_all()
    app = _app(db, SimpleNamespace(id=tenant_id), tmp_path)
    with TestClient(app) as client:
        ok = client.get(f"/api/public/files/{raw}", headers={"host": "a.example.test"})
        mismatch = client.get(f"/api/public/files/{raw}", headers={"host": "b.example.test"})
        trailing_dot_mismatch = client.get(
            f"/api/public/files/{raw}",
            headers={"host": "B.EXAMPLE.TEST.:443"},
        )
        unknown = client.get(
            f"/api/public/files/{raw}",
            headers={"host": "unknown.example.test"},
        )
        expired_raw = "b" * 43
        db.add(PublicAccessToken(
            token_hash=hash_token(expired_raw), tenant_id=tenant_a.id,
            resource_type="stored_file", resource_id=stored_id,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        ))
        db.commit()
        expired = client.get(f"/api/public/files/{expired_raw}")
    assert ok.status_code == 200 and ok.content == b"public"
    assert mismatch.status_code == 403
    assert trailing_dot_mismatch.status_code == 403
    assert unknown.status_code == 400
    assert expired.status_code == 410


def test_main_has_no_public_upload_mount():
    source = Path(__file__).parents[1] / "app" / "main.py"
    text = source.read_text(encoding="utf-8")
    assert 'app.mount("/uploads"' not in text
    assert "StaticFiles" not in text


def test_delete_object_file_never_removes_outside_file(tmp_path, tenant_a):
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"keep")
    with pytest.raises(ValueError):
        delete_object_file(tmp_path, tenant_a.id, "../outside.txt")
    assert outside.exists()


def test_all_business_uploads_use_tenant_storage_and_no_direct_upload_writes():
    app_root = Path(__file__).parents[1] / "app"
    resume_source = (app_root / "services" / "resume_service.py").read_text(encoding="utf-8")
    bank_source = (app_root / "services" / "question_bank_service.py").read_text(encoding="utf-8")
    interview_source = (app_root / "routes" / "interviews.py").read_text(encoding="utf-8")
    assert 'save_upload_file(file, tenant_id, "resumes"' in resume_source
    assert 'save_upload_file(file, tenant_id, "question_banks"' in bank_source
    assert interview_source.count("stored = save_upload_file(") == 3
    assert 'f"uploads/' not in interview_source
    assert "shutil.copyfileobj" not in interview_source
    assert interview_source.count("commit_file_replacement(db, stored, old_files") == 3
    assert interview_source.count('detail="Audio upload failed"') == 3
    for service_name in ("resume_service.py", "question_bank_service.py", "interview_service.py"):
        service_source = (app_root / "services" / service_name).read_text(encoding="utf-8")
        assert "stage_file_deletions" in service_source
        assert "unlink_file_locations" in service_source


def test_audio_temp_and_frontend_blob_lifecycle_have_static_guards():
    root = Path(__file__).parents[2]
    audio_source = (root / "backend" / "app" / "services" / "audio_service.py").read_text(encoding="utf-8")
    hook_source = (root / "frontend" / "src" / "hooks" / "useAuthenticatedFileUrl.ts").read_text(encoding="utf-8")
    bank_source = (root / "frontend" / "src" / "pages" / "QuestionBanks" / "List.tsx").read_text(encoding="utf-8")
    assert "TemporaryDirectory" in audio_source and "finally:" in audio_source
    assert "audio_file_path + \".wav\"" not in audio_source
    assert "AbortController" in hook_source and "revokeObjectURL" in hook_source
    assert "previewGenerationRef" in bank_source and "revokeObjectURL" in bank_source


def test_task_frontend_files_never_log_caught_error_objects():
    root = Path(__file__).parents[2] / "frontend" / "src"
    paths = [
        root / "hooks" / "useAuthenticatedFileUrl.ts",
        root / "pages" / "QuestionBanks" / "List.tsx",
        root / "pages" / "Resumes" / "Detail.tsx",
        root / "pages" / "Interviews" / "Score.tsx",
    ]
    pattern = re.compile(
        r"console\.(?:error|log|warn)\([^\n]*(?:,\s*err(?:or)?\b|event\.error)"
    )
    for path in paths:
        assert pattern.search(path.read_text(encoding="utf-8")) is None, path


def test_business_models_link_new_uploads_to_stored_files():
    from app.models.models import QuestionBank, Resume

    assert hasattr(Resume, "file_id")
    assert hasattr(QuestionBank, "source_file_id")


@pytest.mark.parametrize(
    ("name", "claimed", "expected"),
    [
        ("resume.pdf", "text/html", "application/pdf"),
        ("voice.webm", "text/html\r\nX-Evil: yes", "audio/webm"),
        ("payload.svg", "image/svg+xml", "application/octet-stream"),
        ("unknown.bin", "application/javascript", "application/octet-stream"),
    ],
)
def test_upload_uses_server_mime_allowlist(tmp_path, tenant_a, name, claimed, expected):
    stored = save_upload_file(_upload(name, b"content", claimed), tenant_a.id, "resumes", root=tmp_path)
    assert stored.content_type == expected


def test_authenticated_user_can_issue_short_lived_public_file_token(db, tenant_a, tmp_path):
    stored = save_upload_file(_upload(), tenant_a.id, "resumes", root=tmp_path)
    _bind_resume_file(db, tenant_a.id, stored)
    db.commit()
    app = _app(db, tenant_a, tmp_path)
    with TestClient(app) as client:
        response = client.post(f"/api/files/{stored.id}/public-token", json={"ttl_seconds": 120})
    assert response.status_code == 200
    payload = response.json()
    token_record = db.query(PublicAccessToken).one()
    assert token_record.token_hash == hash_token(payload["token"])
    assert token_record.token_hash != payload["token"]
    assert payload["url"] == f"/api/public/files/{payload['token']}"


@pytest.mark.parametrize("ttl", [0, 86401])
def test_public_file_token_ttl_is_bounded(db, tenant_a, tmp_path, ttl):
    stored = save_upload_file(_upload(), tenant_a.id, "resumes", root=tmp_path)
    _bind_resume_file(db, tenant_a.id, stored)
    db.commit()
    with TestClient(_app(db, tenant_a, tmp_path)) as client:
        response = client.post(f"/api/files/{stored.id}/public-token", json={"ttl_seconds": ttl})
    assert response.status_code == 422


def test_public_file_token_issue_hides_other_tenant_file(db, tenant_a, tenant_b, tmp_path):
    foreign = save_upload_file(_upload(), tenant_b.id, "resumes", root=tmp_path)
    db.add(foreign)
    db.commit()
    with TestClient(_app(db, tenant_a, tmp_path)) as client:
        response = client.post(f"/api/files/{foreign.id}/public-token", json={})
    assert response.status_code == 404


def test_interviewer_cannot_download_or_publish_unassigned_resume_file(
    db, tenant_a, tmp_path
):
    resume_id = uuid4()
    stored = save_upload_file(
        _upload(),
        tenant_a.id,
        "resumes",
        root=tmp_path,
        resource_type="resume",
        resource_id=resume_id,
    )
    resume = Resume(
        id=resume_id,
        tenant_id=tenant_a.id,
        candidate_name="Private Candidate",
        file_id=stored.id,
    )
    db.add_all([stored, resume])
    db.commit()
    interviewer = SimpleNamespace(
        id=uuid4(), tenant_id=tenant_a.id, role=UserRole.INTERVIEWER
    )

    with TestClient(
        _app(db, tenant_a, tmp_path, current_user=interviewer)
    ) as client:
        download = client.get(f"/api/files/{stored.id}")
        publish = client.post(
            f"/api/files/{stored.id}/public-token",
            json={"ttl_seconds": 120},
        )

    assert download.status_code == 404
    assert publish.status_code == 404
    assert db.query(PublicAccessToken).count() == 0


def _unassigned_interviewer(db, tenant_id):
    user = User(
        tenant_id=tenant_id,
        email=f"unassigned-{uuid4().hex}@example.com",
        hashed_password="not-used",
        role=UserRole.INTERVIEWER,
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


def test_unassigned_interviewer_cannot_self_join_panel_by_question_audio_upload(
    db, tenant_a, test_interview, tmp_path, monkeypatch
):
    from app.routes import interviews as interview_routes

    intruder = _unassigned_interviewer(db, tenant_a.id)
    scoped = TenantSession(bind=db.get_bind(), tenant_id=tenant_a.id)
    monkeypatch.setattr(interview_routes, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(interview_routes, "transcribe_audio", lambda _path: {"text": "ok"})

    with pytest.raises(HTTPException) as exc:
        interview_routes.upload_audio_route(
            test_interview.id,
            "0",
            _upload("voice.webm", b"audio", "audio/webm"),
            scoped,
            intruder,
        )

    assert exc.value.status_code == 403
    assert scoped.query(InterviewPanel).filter(
        InterviewPanel.interview_id == test_interview.id,
        InterviewPanel.interviewer_id == intruder.id,
    ).first() is None
    assert scoped.query(StoredFile).count() == 0
    scoped.close()


def test_unassigned_interviewer_cannot_upload_full_interview_audio(
    db, tenant_a, test_interview, tmp_path, monkeypatch
):
    from app.routes import interviews as interview_routes
    from app.services import audio_service

    intruder = _unassigned_interviewer(db, tenant_a.id)
    scoped = TenantSession(bind=db.get_bind(), tenant_id=tenant_a.id)
    monkeypatch.setattr(interview_routes, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(audio_service, "transcribe_audio", lambda _path: {"text": "ok", "segments": []})
    monkeypatch.setattr(audio_service, "format_transcript_for_display", lambda _data: "ok")

    with pytest.raises(HTTPException) as exc:
        interview_routes.upload_full_interview_audio(
            test_interview.id,
            _upload("voice.webm", b"audio", "audio/webm"),
            BackgroundTasks(),
            scoped,
            intruder,
        )

    assert exc.value.status_code == 403
    assert scoped.query(StoredFile).count() == 0
    scoped.close()


def test_unassigned_interviewer_cannot_upload_direct_evaluation_audio(
    db, tenant_a, test_interview, tmp_path, monkeypatch
):
    from app.routes import interviews as interview_routes
    from app.services import audio_service

    intruder = _unassigned_interviewer(db, tenant_a.id)
    scoped = TenantSession(bind=db.get_bind(), tenant_id=tenant_a.id)
    monkeypatch.setattr(interview_routes, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(audio_service, "transcribe_audio", lambda _path: {"text": "ok"})

    with pytest.raises(HTTPException) as exc:
        interview_routes.submit_direct_evaluation_with_audio(
            test_interview.id,
            BackgroundTasks(),
            _upload("voice.webm", b"audio", "audio/webm"),
            "evaluation",
            "suggestion",
            5,
            scoped,
            intruder,
        )

    assert exc.value.status_code == 403
    assert scoped.query(StoredFile).count() == 0
    scoped.close()


def test_unassigned_interviewer_cannot_issue_interview_audio_public_token(
    db, tenant_a, test_interview, tmp_path
):
    intruder = _unassigned_interviewer(db, tenant_a.id)
    stored = save_upload_file(
        _upload("voice.webm", b"audio", "audio/webm"),
        tenant_a.id,
        "interview_audio",
        root=tmp_path,
        resource_type="interview",
        resource_id=test_interview.id,
    )
    db.add(stored)
    db.commit()

    with TestClient(
        _app(db, tenant_a, tmp_path, current_user=intruder)
    ) as client:
        response = client.post(
            f"/api/files/{stored.id}/public-token",
            json={"ttl_seconds": 120},
        )

    assert response.status_code == 404
    assert db.query(PublicAccessToken).count() == 0


def test_unassigned_interviewer_cannot_download_interview_audio(
    db, tenant_a, test_interview, tmp_path
):
    intruder = _unassigned_interviewer(db, tenant_a.id)
    stored = save_upload_file(
        _upload("voice.webm", b"audio", "audio/webm"),
        tenant_a.id,
        "interview_audio",
        root=tmp_path,
        resource_type="interview",
        resource_id=test_interview.id,
    )
    db.add(stored)
    db.commit()

    with TestClient(
        _app(db, tenant_a, tmp_path, current_user=intruder)
    ) as client:
        response = client.get(f"/api/files/{stored.id}")

    assert response.status_code == 404


def test_replacement_commit_removes_old_metadata_and_file(db, tenant_a, tmp_path):
    old = save_upload_file(_upload("old.pdf", b"old"), tenant_a.id, "resumes", root=tmp_path)
    db.add(old)
    db.commit()
    old_path = resolve_object_path(tmp_path, tenant_a.id, old.object_key)
    new = save_upload_file(_upload("new.pdf", b"new"), tenant_a.id, "resumes", root=tmp_path)
    db.add(new)
    commit_file_replacement(db, new, [old], root=tmp_path)
    assert db.query(StoredFile).filter(StoredFile.id == old.id).first() is None
    assert db.query(StoredFile).filter(StoredFile.id == new.id).first() is not None
    assert not old_path.exists()
    assert resolve_object_path(tmp_path, tenant_a.id, new.object_key).exists()


def test_replacement_commit_failure_preserves_old_and_cleans_new(
    db, tenant_a, tmp_path, monkeypatch
):
    old = save_upload_file(_upload("old.pdf", b"old"), tenant_a.id, "resumes", root=tmp_path)
    db.add(old)
    db.commit()
    old_id = old.id
    old_path = resolve_object_path(tmp_path, tenant_a.id, old.object_key)
    new = save_upload_file(_upload("new.pdf", b"new"), tenant_a.id, "resumes", root=tmp_path)
    new_path = resolve_object_path(tmp_path, tenant_a.id, new.object_key)
    db.add(new)
    real_commit = db.commit
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("db unavailable")))
    with pytest.raises(RuntimeError, match="db unavailable"):
        commit_file_replacement(db, new, [old], root=tmp_path)
    monkeypatch.setattr(db, "commit", real_commit)
    assert db.query(StoredFile).filter(StoredFile.id == old_id).first() is not None
    assert old_path.exists()
    assert not new_path.exists()


def test_delete_resume_revokes_download_and_unlinks_file(
    db, tenant_a, test_resume, tmp_path, monkeypatch
):
    from app.services import resume_service

    stored = save_upload_file(
        _upload(), tenant_a.id, "resumes", root=tmp_path,
        resource_type="resume", resource_id=test_resume.id,
    )
    path = resolve_object_path(tmp_path, tenant_a.id, stored.object_key)
    test_resume.file_id = stored.id
    test_resume.file_path = f"/api/files/{stored.id}"
    db.add(stored)
    db.commit()
    monkeypatch.setattr(resume_service, "UPLOAD_ROOT", tmp_path)
    resume_service.delete_resume(db, test_resume.id)
    assert db.query(StoredFile).filter(StoredFile.id == stored.id).first() is None
    assert not path.exists()
    with TestClient(_app(db, tenant_a, tmp_path)) as client:
        assert client.get(f"/api/files/{stored.id}").status_code == 404


def test_delete_interview_revokes_all_audio_files(
    db, tenant_a, test_interview, tmp_path, monkeypatch
):
    from app.services import interview_service

    stored = save_upload_file(
        _upload("voice.webm", b"audio"), tenant_a.id, "interview_audio", root=tmp_path,
        resource_type="interview", resource_id=test_interview.id,
    )
    path = resolve_object_path(tmp_path, tenant_a.id, stored.object_key)
    test_interview.audio_records = {"full_interview": f"/api/files/{stored.id}"}
    db.add(stored)
    db.commit()
    monkeypatch.setattr(interview_service, "UPLOAD_ROOT", tmp_path)
    interview_service.delete_interview(db, test_interview.id)
    assert db.query(StoredFile).filter(StoredFile.id == stored.id).first() is None
    assert not path.exists()


def test_replacement_url_lookup_is_strict_and_tenant_scoped(db, tenant_a, tenant_b, tmp_path):
    own = save_upload_file(
        _upload("voice.webm"), tenant_a.id, "interview_audio", root=tmp_path,
        resource_type="interview", resource_id=uuid4(),
    )
    foreign = save_upload_file(
        _upload("voice.webm"), tenant_b.id, "interview_audio", root=tmp_path,
        resource_type="interview", resource_id=own.resource_id,
    )
    db.add_all([own, foreign])
    db.commit()
    urls = [f"/api/files/{own.id}", f"/api/files/{foreign.id}", "../../secret", "/uploads/old.wav"]
    found = tenant_files_from_urls(
        db, tenant_a.id, "interview", own.resource_id, "interview_audio", urls
    )
    assert [item.id for item in found] == [own.id]


def test_question_audio_transcription_failure_leaves_no_metadata_or_file(
    db, tenant_a, test_interview, test_interviewer, tmp_path, monkeypatch
):
    from app.routes import interviews as interview_routes

    scoped = TenantSession(bind=db.get_bind(), tenant_id=tenant_a.id)
    monkeypatch.setattr(interview_routes, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(
        interview_routes, "transcribe_audio",
        lambda _path: (_ for _ in ()).throw(RuntimeError("provider detail")),
    )
    with pytest.raises(HTTPException) as exc:
        interview_routes.upload_audio_route(
            test_interview.id, "0", _upload("voice.webm", b"audio", "audio/webm"),
            scoped, test_interviewer,
        )
    assert exc.value.detail == "Audio upload failed"
    assert scoped.query(StoredFile).count() == 0
    assert not list(tmp_path.rglob("*.*"))
    scoped.close()


def test_full_audio_business_failure_leaves_no_metadata_or_file(
    db, tenant_a, test_interview, test_interviewer, tmp_path, monkeypatch
):
    from app.routes import interviews as interview_routes
    from app.services import audio_service

    scoped = TenantSession(bind=db.get_bind(), tenant_id=tenant_a.id)
    monkeypatch.setattr(interview_routes, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(audio_service, "transcribe_audio", lambda _path: {"text": "ok", "segments": []})
    monkeypatch.setattr(
        audio_service, "format_transcript_for_display",
        lambda _data: (_ for _ in ()).throw(RuntimeError("format detail")),
    )
    with pytest.raises(HTTPException) as exc:
        interview_routes.upload_full_interview_audio(
            test_interview.id, _upload("voice.webm", b"audio", "audio/webm"),
            BackgroundTasks(), scoped, test_interviewer,
        )
    assert exc.value.detail == "Audio upload failed"
    assert scoped.query(StoredFile).count() == 0
    assert not list(tmp_path.rglob("*.*"))
    scoped.close()
