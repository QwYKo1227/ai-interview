from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient

from app.config.database import get_unscoped_db
from app.models.models import (
    CodingSubmission, CodingTest, CodingTestStatus, DepartmentReview, Offer, OfferStatus,
    Position, PositionStatus, ResumeStatus,
)
from app.models.tenant_models import PublicAccessToken, Tenant, TenantDomain, TenantStatus
from app.models.file_models import StoredFile
from app.routes import coding_tests, files, positions, public_review, resumes
from app.routes.auth import get_current_user
from app.routes.offers import public_router as offer_public_router
from app.services import offer_service, resume_service
from app.services.public_token_service import (
    hash_token,
    issue_public_token,
    resolve_public_token,
)
from app.utils.file_storage import save_upload_file


def _offer(db, tenant, *, email="candidate@example.com"):
    position = Position(
        tenant_id=tenant.id,
        title="Backend Engineer",
        description="Build services",
        requirements="Python",
        status=PositionStatus.OPEN,
    )
    db.add(position)
    db.flush()
    offer = Offer(
        tenant_id=tenant.id,
        resume_id=uuid4(),
        position_id=position.id,
        candidate_name="Candidate",
        candidate_email=email,
        position_title=position.title,
        status=OfferStatus.SENT,
    )
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return offer


@pytest.fixture(autouse=True)
def offer_table(db):
    Offer.__table__.create(bind=db.get_bind(), checkfirst=True)
    yield
    Offer.__table__.drop(bind=db.get_bind(), checkfirst=True)


def test_public_token_resolves_exact_tenant_and_never_stores_raw(db, tenant_a):
    offer = _offer(db, tenant_a)
    tenant_id = tenant_a.id
    offer_id = offer.id
    raw = issue_public_token(
        db,
        tenant_id=tenant_id,
        resource_type="offer",
        resource_id=offer_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )

    stored = db.query(PublicAccessToken).one()
    assert len(raw) >= 43
    assert stored.token_hash == hash_token(raw)
    assert stored.token_hash != raw
    assert raw not in repr(stored.__dict__)

    db.expunge_all()
    resolved = resolve_public_token(db, raw, "offer")
    assert resolved.tenant_id == tenant_id
    assert resolved.resource_id == offer_id
    assert resolved.resource.id == offer_id


@pytest.mark.parametrize("resource_type", ["unknown", "", "resume"])
def test_issue_rejects_unsupported_resource_type(db, tenant_a, resource_type):
    with pytest.raises(ValueError, match="resource type"):
        issue_public_token(
            db,
            tenant_a.id,
            resource_type,
            uuid4(),
            datetime.now(timezone.utc) + timedelta(days=1),
        )


def test_issue_rejects_cross_tenant_resource_and_inactive_tenant(db, tenant_a, tenant_b):
    offer = _offer(db, tenant_a)
    future = datetime.now(timezone.utc) + timedelta(days=1)

    with pytest.raises(HTTPException) as cross_tenant:
        issue_public_token(db, tenant_b.id, "offer", offer.id, future)
    assert cross_tenant.value.status_code == 404

    tenant_a.status = TenantStatus.DISABLED
    db.commit()
    with pytest.raises(HTTPException) as inactive:
        issue_public_token(db, tenant_a.id, "offer", offer.id, future)
    assert inactive.value.status_code == 404


def test_issue_requires_timezone_aware_future_expiry(db, tenant_a):
    offer = _offer(db, tenant_a)
    with pytest.raises(ValueError, match="timezone-aware"):
        issue_public_token(db, tenant_a.id, "offer", offer.id, datetime.utcnow())
    with pytest.raises(ValueError, match="future"):
        issue_public_token(
            db,
            tenant_a.id,
            "offer",
            offer.id,
            datetime.now(timezone.utc) - timedelta(seconds=1),
        )


def test_resolve_masks_unknown_type_mismatch_revoked_and_deleted_resource(db, tenant_a):
    offer = _offer(db, tenant_a)
    raw = issue_public_token(
        db,
        tenant_a.id,
        "offer",
        offer.id,
        datetime.now(timezone.utc) + timedelta(days=1),
    )

    for candidate, resource_type in (("unknown", "offer"), (raw, "coding_test")):
        with pytest.raises(HTTPException) as exc:
            resolve_public_token(db, candidate, resource_type)
        assert exc.value.status_code == 404
        assert exc.value.detail == "Public resource not found"

    record = db.query(PublicAccessToken).one()
    record.revoked_at = datetime.now(timezone.utc)
    db.commit()
    with pytest.raises(HTTPException) as revoked:
        resolve_public_token(db, raw, "offer")
    assert revoked.value.status_code == 404

    record.revoked_at = None
    db.delete(offer)
    db.commit()
    db.expunge_all()
    with pytest.raises(HTTPException) as deleted:
        resolve_public_token(db, raw, "offer")
    assert deleted.value.status_code == 404


def test_resolve_expired_token_returns_gone(db, tenant_a):
    offer = _offer(db, tenant_a)
    raw = issue_public_token(
        db,
        tenant_a.id,
        "offer",
        offer.id,
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    record = db.query(PublicAccessToken).one()
    record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()

    with pytest.raises(HTTPException) as expired:
        resolve_public_token(db, raw, "offer")
    assert expired.value.status_code == 410
    assert expired.value.detail == "Public link expired"


def test_reissuing_resource_token_revokes_previous_link(db, tenant_a):
    offer = _offer(db, tenant_a)
    offer_id = offer.id
    expires = datetime.now(timezone.utc) + timedelta(days=1)
    first = issue_public_token(db, tenant_a.id, "offer", offer.id, expires)
    second = issue_public_token(db, tenant_a.id, "offer", offer.id, expires)
    db.expunge_all()

    with pytest.raises(HTTPException) as old_link:
        resolve_public_token(db, first, "offer")
    assert old_link.value.status_code == 404
    assert resolve_public_token(db, second, "offer").resource_id == offer_id


def _client(db, *routers, current_user=None):
    app = FastAPI()
    for router in routers:
        app.include_router(router, prefix="/api")

    def override_db():
        yield db

    app.dependency_overrides[get_unscoped_db] = override_db
    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user
    return TestClient(app)


def test_offer_public_route_confirms_with_token_and_rejects_domain_mismatch(db, tenant_a, tenant_b):
    offer = _offer(db, tenant_a)
    raw = issue_public_token(
        db, tenant_a.id, "offer", offer.id,
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    db.add(TenantDomain(tenant_id=tenant_b.id, domain="other.example.com", is_primary=True))
    db.commit()
    db.expunge_all()
    client = _client(db, offer_public_router)

    mismatch = client.get(f"/api/public/offers/confirm/{raw}", headers={"host": "other.example.com"})
    assert mismatch.status_code == 403


def test_coding_public_routes_use_hashed_token_and_copy_tenant_to_submission(db, tenant_a):
    coding_test = CodingTest(
        tenant_id=tenant_a.id, title="Choice", test_type="choice",
        public_token=hash_token("disabled-legacy"), status=CodingTestStatus.PUBLISHED,
        questions=[{"id": "q1", "question": "2+2", "correct_answer": "4", "score": 10}],
    )
    db.add(coding_test)
    db.commit()
    raw = issue_public_token(
        db, tenant_a.id, "coding_test", coding_test.id,
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    tenant_id = tenant_a.id
    db.expunge_all()
    client = _client(db, coding_tests.public_router)

    response = client.get(f"/api/public/coding-tests/{raw}")
    assert response.status_code == 200
    assert "correct_answer" not in response.json()["questions"][0]
    submitted = client.post(
        f"/api/public/coding-tests/{raw}/submit-choice",
        json={"candidate_name": "A", "candidate_email": "a@example.com", "answers": [{"question_id": "q1", "answer": "4"}]},
    )
    assert submitted.status_code == 200
    stored_submission = db.query(CodingSubmission).filter(
        CodingSubmission.id == UUID(submitted.json()["id"])
    ).one()
    assert stored_submission.tenant_id == tenant_id


def test_review_public_route_uses_precreated_review_token_not_reviewer_query(db, tenant_a, test_resume, test_user):
    review = DepartmentReview(
        tenant_id=tenant_a.id, resume_id=test_resume.id,
        reviewer_id=test_user.id, is_completed=False,
    )
    db.add(review)
    db.commit()
    raw = issue_public_token(
        db, tenant_a.id, "department_review", review.id,
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    resume_id = test_resume.id
    reviewer_id = test_user.id
    authenticated_reviewer = SimpleNamespace(id=reviewer_id)
    db.expunge_all()
    client = _client(db, public_review.router, current_user=authenticated_reviewer)

    legacy = client.get(f"/api/public/review/{resume_id}?reviewer_id={reviewer_id}")
    assert legacy.status_code == 404
    response = client.get(f"/api/public/review/{raw}")
    assert response.status_code == 200
    assert response.json()["completed"] is False
    assert response.json()["resume"]["file_available"] is False
    submitted = client.post(
        f"/api/public/review/{raw}/submit",
        json={"technical_score": 8, "overall_score": 8, "recommendation": "recommend", "comment": "ok"},
    )
    assert submitted.status_code == 200

    reopened = client.get(f"/api/public/review/{raw}")
    assert reopened.status_code == 200
    assert reopened.json() == {"completed": True}

    repeated = client.post(
        f"/api/public/review/{raw}/submit",
        json={"technical_score": 9, "overall_score": 9, "recommendation": "recommend"},
    )
    assert repeated.status_code == 404
    token_record = db.query(PublicAccessToken).filter(
        PublicAccessToken.token_hash == hash_token(raw)
    ).one()
    assert token_record.revoked_at is None

    token_record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    expired = client.get(f"/api/public/review/{raw}")
    assert expired.status_code == 410


def test_review_resume_file_is_available_only_while_review_is_active(
    db, tenant_a, test_resume, test_user, tmp_path, monkeypatch
):
    stored = save_upload_file(
        UploadFile(filename="candidate.pdf", file=BytesIO(b"resume-pdf")),
        tenant_a.id,
        "resumes",
        root=tmp_path,
        resource_type="resume",
        resource_id=test_resume.id,
    )
    db.add(stored)
    db.flush()
    test_resume.file_id = stored.id
    review = DepartmentReview(
        tenant_id=tenant_a.id,
        resume_id=test_resume.id,
        reviewer_id=test_user.id,
        is_completed=False,
    )
    db.add(review)
    db.commit()
    raw = issue_public_token(
        db, tenant_a.id, "department_review", review.id,
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    authenticated_reviewer = SimpleNamespace(id=test_user.id)
    db.expunge_all()
    monkeypatch.setattr(files, "UPLOAD_ROOT", tmp_path)
    client = _client(db, public_review.router, current_user=authenticated_reviewer)

    active = client.get(f"/api/public/review/{raw}/resume-file")
    assert active.status_code == 200
    assert active.content == b"resume-pdf"
    assert active.headers["content-type"] == "application/pdf"

    submitted = client.post(
        f"/api/public/review/{raw}/submit",
        json={"recommendation": "recommend"},
    )
    assert submitted.status_code == 200
    blocked = client.get(f"/api/public/review/{raw}/resume-file")
    assert blocked.status_code == 404


def test_review_resume_file_rejects_mismatched_stored_file(
    db, tenant_a, test_resume, test_user, tmp_path, monkeypatch
):
    stored = save_upload_file(
        UploadFile(filename="other.pdf", file=BytesIO(b"other")),
        tenant_a.id,
        "resumes",
        root=tmp_path,
        resource_type="resume",
        resource_id=uuid4(),
    )
    db.add(stored)
    db.flush()
    test_resume.file_id = stored.id
    review = DepartmentReview(
        tenant_id=tenant_a.id, resume_id=test_resume.id,
        reviewer_id=test_user.id, is_completed=False,
    )
    db.add(review)
    db.commit()
    raw = issue_public_token(
        db, tenant_a.id, "department_review", review.id,
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    authenticated_reviewer = SimpleNamespace(id=test_user.id)
    db.expunge_all()
    monkeypatch.setattr(files, "UPLOAD_ROOT", tmp_path)
    client = _client(db, public_review.router, current_user=authenticated_reviewer)

    response = client.get(f"/api/public/review/{raw}/resume-file")
    assert response.status_code == 404
    assert response.json()["detail"] == "Public resource not found"


def test_public_positions_are_tenant_scoped_and_legacy_global_list_is_closed(db, tenant_a, tenant_b):
    db.add_all([
        Position(tenant_id=tenant_a.id, title="A Role", description="A", requirements="A", status=PositionStatus.PUBLISHED),
        Position(tenant_id=tenant_b.id, title="B Role", description="B", requirements="B", status=PositionStatus.PUBLISHED),
    ])
    db.commit()
    db.expunge_all()
    client = _client(db, positions.router, positions.public_router)

    response = client.get("/api/public/careray/positions")
    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == ["A Role"]


def test_public_route_source_has_no_direct_unscoped_business_query():
    for module in (coding_tests, positions, public_review):
        source = __import__("inspect").getsource(module)
        assert "Depends(get_unscoped_db)" not in source or "db.query(Resume)" not in source


@pytest.mark.parametrize("mail_behavior", [False, RuntimeError("smtp failed")])
def test_offer_mail_failure_revokes_token_and_restores_retryable_state(
    db, tenant_a, test_resume, monkeypatch, mail_behavior
):
    offer = _offer(db, tenant_a)
    test_resume.status = ResumeStatus.INTERVIEW_PASSED
    offer.resume_id = test_resume.id
    offer.status = OfferStatus.PENDING
    db.commit()
    known_raw = "A" * 43
    monkeypatch.setattr("app.services.public_token_service.secrets.token_urlsafe", lambda _n: known_raw)

    class Mailer:
        def __init__(self, _db):
            pass

        def send_offer_email(self, **_kwargs):
            if isinstance(mail_behavior, Exception):
                raise mail_behavior
            return mail_behavior

    monkeypatch.setattr(offer_service, "MailService", Mailer)
    result = offer_service.send_offer(db, offer.id, send_email=True)

    db.refresh(offer)
    assert result == {
        "success": False,
        "email_sent": False,
        "error": "Failed to send offer email",
        "token": None,
    }
    assert offer.status == OfferStatus.PENDING
    db.refresh(test_resume)
    assert test_resume.status == ResumeStatus.INTERVIEW_PASSED
    db.expunge_all()
    with pytest.raises(HTTPException) as invalid:
        resolve_public_token(db, known_raw, "offer")
    assert invalid.value.status_code == 404


@pytest.mark.parametrize("send_email", [False, True])
def test_successful_offer_send_moves_resume_to_offer_pending(
    db, tenant_a, test_resume, monkeypatch, send_email
):
    offer = _offer(db, tenant_a)
    test_resume.status = ResumeStatus.INTERVIEW_PASSED
    offer.resume_id = test_resume.id
    offer.status = OfferStatus.PENDING
    db.commit()

    class Mailer:
        def __init__(self, _db):
            pass

        def send_offer_email(self, **_kwargs):
            return True

    monkeypatch.setattr(offer_service, "MailService", Mailer)
    result = offer_service.send_offer(db, offer.id, send_email=send_email)

    db.refresh(test_resume)
    assert result["success"] is True
    assert result["email_sent"] is send_email
    assert result["token"]
    assert test_resume.status == ResumeStatus.OFFER_PENDING


def test_offer_can_be_sent_successfully_after_mail_failure(db, tenant_a, monkeypatch):
    offer = _offer(db, tenant_a)
    offer.status = OfferStatus.PENDING
    db.commit()

    outcomes = iter([False, True])

    class Mailer:
        def __init__(self, _db):
            pass

        def send_offer_email(self, **_kwargs):
            return next(outcomes)

    monkeypatch.setattr(offer_service, "MailService", Mailer)
    first = offer_service.send_offer(db, offer.id, send_email=True)
    second = offer_service.send_offer(db, offer.id, send_email=True)
    offer_id = offer.id
    assert first["success"] is False
    assert second["success"] is True
    assert second["email_sent"] is True
    db.expunge_all()
    assert resolve_public_token(db, second["token"], "offer").resource_id == offer_id


@pytest.mark.parametrize("raw", ["", "x" * 39, "x" * 129, "bad token!" * 5])
def test_resolve_rejects_malformed_token_before_hashing(db, monkeypatch, raw):
    def should_not_hash(_raw):
        raise AssertionError("malformed token must not be hashed")

    monkeypatch.setattr("app.services.public_token_service.hash_token", should_not_hash)
    with pytest.raises(HTTPException) as invalid:
        resolve_public_token(db, raw, "offer")
    assert invalid.value.status_code == 404


def test_coding_legacy_marker_is_not_bearer_and_reissue_revokes_old(db, tenant_a):
    coding_test = CodingTest(
        tenant_id=tenant_a.id, title="Public", public_token=hash_token("legacy"),
        status=CodingTestStatus.PUBLISHED,
    )
    db.add(coding_test)
    db.commit()
    first = issue_public_token(
        db, tenant_a.id, "coding_test", coding_test.id,
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    coding_test_id = coding_test.id
    tenant_id = tenant_a.id
    db.expunge_all()
    from app.config.tenant_session import set_tenant_context
    set_tenant_context(db, tenant_id)
    from app.services.coding_test_service import reissue_coding_test_public_token
    second = reissue_coding_test_public_token(db, coding_test_id)
    db.expunge_all()
    with pytest.raises(HTTPException):
        resolve_public_token(db, first, "coding_test")
    with pytest.raises(HTTPException):
        resolve_public_token(db, hash_token("legacy"), "coding_test")
    assert resolve_public_token(db, second, "coding_test").resource_id == coding_test_id


def test_review_submit_validation_returns_422_without_writing(db, tenant_a, test_resume, test_user):
    review = DepartmentReview(
        tenant_id=tenant_a.id, resume_id=test_resume.id,
        reviewer_id=test_user.id, is_completed=False,
    )
    db.add(review)
    db.commit()
    raw = issue_public_token(
        db, tenant_a.id, "department_review", review.id,
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    review_id = review.id
    authenticated_reviewer = SimpleNamespace(id=test_user.id)
    db.expunge_all()
    client = _client(db, public_review.router, current_user=authenticated_reviewer)
    response = client.post(
        f"/api/public/review/{raw}/submit",
        json={"technical_score": 0, "overall_score": 11, "recommendation": "invalid", "comment": "x"},
    )
    assert response.status_code == 422
    assert db.query(DepartmentReview).filter(DepartmentReview.id == review_id).one().is_completed is False


def test_public_resume_upload_requires_tenant_and_published_position(
    db, tenant_a, test_position, monkeypatch
):
    test_position.status = PositionStatus.PUBLISHED
    db.commit()
    monkeypatch.setattr("app.services.resume_service.save_upload_file", lambda *_args, **_kwargs: StoredFile(
        id=uuid4(), tenant_id=_args[1], object_key=f"{_args[1]}/resumes/test.pdf",
        original_filename="test.pdf", content_type="application/pdf", size=8, category="resumes",
    ))
    monkeypatch.setattr("app.services.resume_service.process_resume_background", lambda *_args: None)
    position_id = test_position.id
    db.expunge_all()
    client = _client(db, resumes.router)

    missing = client.post(
        "/api/resumes",
        data={"position_id": str(position_id)},
        files={"file": ("resume.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert missing.status_code == 404

    accepted = client.post(
        "/api/resumes",
        data={"position_id": str(position_id), "tenant_code": "careray"},
        files={"file": ("resume.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert accepted.status_code == 200
    assert accepted.json()["position_id"] == str(position_id)


def test_offer_atomic_transition_does_not_overwrite_completed_state(db, tenant_a):
    offer = _offer(db, tenant_a)
    raw = issue_public_token(
        db, tenant_a.id, "offer", offer.id,
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    offer.status = OfferStatus.ACCEPTED
    offer.accepted_at = datetime.utcnow()
    db.commit()
    offer_id = offer.id
    accepted_at = offer.accepted_at
    db.expunge_all()
    with pytest.raises(HTTPException) as conflict:
        offer_service.confirm_offer_by_token(db, raw, "reject", reason="late")
    assert conflict.value.status_code == 404
    stored = db.query(Offer).filter(Offer.id == offer_id).one()
    assert stored.status == OfferStatus.ACCEPTED
    assert stored.accepted_at == accepted_at
    assert stored.rejected_reason is None


def test_review_atomic_transition_does_not_overwrite_completed_state(
    db, tenant_a, test_resume, test_user
):
    review = DepartmentReview(
        tenant_id=tenant_a.id, resume_id=test_resume.id,
        reviewer_id=test_user.id, is_completed=False,
    )
    db.add(review)
    db.commit()
    raw = issue_public_token(
        db, tenant_a.id, "department_review", review.id,
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    review.is_completed = True
    review.overall_score = 7
    review.comment = "first"
    review_id = review.id
    db.commit()
    db.expunge_all()
    resolved = resolve_public_token(db, raw, "department_review")
    with pytest.raises(HTTPException) as conflict:
        resume_service.submit_public_department_review(
            db, resolved.resource, technical_score=None, experience_score=None,
            overall_score=10, recommendation="recommend", comment="overwrite",
        )
    assert conflict.value.status_code == 404
    stored = db.query(DepartmentReview).filter(DepartmentReview.id == review_id).one()
    assert stored.overall_score == 7
    assert stored.comment == "first"


def test_public_resume_upload_rejects_host_conflict_cross_tenant_and_unpublished(
    db, tenant_a, tenant_b, test_position, monkeypatch
):
    other = Position(
        tenant_id=tenant_b.id, title="Other", description="Other",
        requirements="Other", status=PositionStatus.PUBLISHED,
    )
    db.add(other)
    db.add(TenantDomain(tenant_id=tenant_b.id, domain="other.example.com", is_primary=True))
    db.commit()
    monkeypatch.setattr("app.services.resume_service.save_upload_file", lambda *_args, **_kwargs: StoredFile(
        id=uuid4(), tenant_id=_args[1], object_key=f"{_args[1]}/resumes/test.pdf",
        original_filename="test.pdf", content_type="application/pdf", size=8, category="resumes",
    ))
    other_id, own_id = other.id, test_position.id
    db.expunge_all()
    client = _client(db, resumes.router)

    conflict = client.post(
        "/api/resumes", headers={"host": "other.example.com"},
        data={"position_id": str(own_id), "tenant_code": "careray"},
        files={"file": ("resume.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert conflict.status_code == 403
    cross = client.post(
        "/api/resumes",
        data={"position_id": str(other_id), "tenant_code": "careray"},
        files={"file": ("resume.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert cross.status_code == 404
    unpublished = client.post(
        "/api/resumes",
        data={"position_id": str(own_id), "tenant_code": "careray"},
        files={"file": ("resume.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert unpublished.status_code == 404
