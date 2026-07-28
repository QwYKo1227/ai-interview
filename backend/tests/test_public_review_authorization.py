from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.database import get_unscoped_db
from app.models.models import DepartmentReview
from app.routes import public_review
from app.routes.auth import get_current_user
from app.services.public_token_service import issue_public_token


def _client(db, current_user=None):
    app = FastAPI()
    app.include_router(public_review.router, prefix="/api")

    def override_db():
        yield db

    app.dependency_overrides[get_unscoped_db] = override_db
    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user
    return TestClient(app)


def test_public_review_requires_the_assigned_authenticated_reviewer(
    db, tenant_a, test_resume, test_user, test_admin
):
    review = DepartmentReview(
        tenant_id=tenant_a.id,
        resume_id=test_resume.id,
        reviewer_id=test_user.id,
        is_completed=False,
    )
    db.add(review)
    db.commit()
    raw_token = issue_public_token(
        db,
        tenant_a.id,
        "department_review",
        review.id,
        datetime.now(timezone.utc) + timedelta(days=1),
    )
    assigned_user_id = test_user.id
    wrong_user_id = test_admin.id
    db.expunge_all()

    unauthenticated = _client(db).get(f"/api/public/review/{raw_token}")
    assert unauthenticated.status_code == 401

    wrong_user_client = _client(db, SimpleNamespace(id=wrong_user_id))
    wrong_user = wrong_user_client.get(f"/api/public/review/{raw_token}")
    assert wrong_user.status_code == 403
    wrong_file_access = wrong_user_client.get(
        f"/api/public/review/{raw_token}/resume-file"
    )
    assert wrong_file_access.status_code == 403
    wrong_submission = wrong_user_client.post(
        f"/api/public/review/{raw_token}/submit",
        json={"recommendation": "recommend"},
    )
    assert wrong_submission.status_code == 403

    assigned_user = _client(db, SimpleNamespace(id=assigned_user_id)).get(
        f"/api/public/review/{raw_token}"
    )
    assert assigned_user.status_code == 200
