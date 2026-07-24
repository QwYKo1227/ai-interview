from uuid import uuid4

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.models import Position, Resume, ResumeStatus


def test_filters_resumes_by_position_id(
    client: TestClient,
    auth_headers: dict,
    db: Session,
    test_resume: Resume,
    test_position: Position,
):
    other_position = Position(
        id=uuid4(),
        title="Other Position",
        description="Other position description",
    )
    db.add(other_position)
    db.commit()
    db.refresh(other_position)

    other_resume = Resume(
        id=uuid4(),
        candidate_name="Other Candidate",
        contact="13900000000",
        email="other@example.com",
        position_id=other_position.id,
        file_path="/uploads/other.pdf",
        status=ResumeStatus.PENDING_SCREENING,
    )
    db.add(other_resume)
    db.commit()

    response = client.get(
        "/api/resumes",
        params={"position_id": str(test_position.id)},
        headers=auth_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()
    assert {item["position_id"] for item in response.json()} == {
        str(test_position.id)
    }
