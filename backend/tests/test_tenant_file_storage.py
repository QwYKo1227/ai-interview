import os
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient

from app.config.database import get_unscoped_db
from app.core.tenant_dependencies import get_current_user_dep, get_tenant_db
from app.models.file_models import StoredFile
from app.models.tenant_models import PublicAccessToken, TenantDomain
from app.routes import files
from app.services.public_token_service import hash_token
from app.utils.file_storage import (
    MAX_UPLOAD_SIZE,
    delete_object_file,
    resolve_object_path,
    save_upload_file,
)


def _upload(name="candidate.pdf", content=b"resume", content_type="application/pdf"):
    return UploadFile(filename=name, file=BytesIO(content), headers={"content-type": content_type})


def _app(db, tenant, root):
    app = FastAPI()
    app.include_router(files.router, prefix="/api")
    app.include_router(files.public_router, prefix="/api")
    app.dependency_overrides[get_tenant_db] = lambda: db
    app.dependency_overrides[get_unscoped_db] = lambda: db
    app.dependency_overrides[get_current_user_dep] = lambda: SimpleNamespace(
        id=uuid4(), tenant_id=tenant.id
    )
    files.UPLOAD_ROOT = root
    return app


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
    db.add_all([own, foreign])
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
    assert interview_source.count('save_upload_file(file, tenant_id, "interview_audio"') == 3
    assert 'f"uploads/' not in interview_source
    assert "shutil.copyfileobj" not in interview_source


def test_business_models_link_new_uploads_to_stored_files():
    from app.models.models import QuestionBank, Resume

    assert hasattr(Resume, "file_id")
    assert hasattr(QuestionBank, "source_file_id")
