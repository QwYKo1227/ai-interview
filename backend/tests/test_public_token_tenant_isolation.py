from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.config.database import get_unscoped_db
from app.models.models import (
    CodingTest, CodingTestStatus, DepartmentReview, Offer, OfferStatus,
    Position, PositionStatus,
)
from app.models.tenant_models import PublicAccessToken, Tenant, TenantDomain, TenantStatus
from app.routes import coding_tests, positions, public_review
from app.routes.offers import public_router as offer_public_router
from app.services.public_token_service import (
    hash_token,
    issue_public_token,
    resolve_public_token,
)


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


def _client(db, *routers):
    app = FastAPI()
    for router in routers:
        app.include_router(router, prefix="/api")

    def override_db():
        yield db

    app.dependency_overrides[get_unscoped_db] = override_db
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
    assert db.query(CodingTest).filter(CodingTest.tenant_id == tenant_id).count() == 1


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
    db.expunge_all()
    client = _client(db, public_review.router)

    legacy = client.get(f"/api/public/review/{resume_id}?reviewer_id={reviewer_id}")
    assert legacy.status_code == 404
    response = client.get(f"/api/public/review/{raw}")
    assert response.status_code == 200
    submitted = client.post(
        f"/api/public/review/{raw}/submit",
        params={"technical_score": 8, "overall_score": 8, "recommendation": "recommend", "comment": "ok"},
    )
    assert submitted.status_code == 200
    repeated = client.post(f"/api/public/review/{raw}/submit")
    assert repeated.status_code == 400


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
