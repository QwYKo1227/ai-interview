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
        tenant_id=test_position.tenant_id,
        title="Other Position",
        description="Other position description",
    )
    db.add(other_position)
    db.commit()
    db.refresh(other_position)

    other_resume = Resume(
        id=uuid4(),
        tenant_id=test_position.tenant_id,
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


def test_lists_and_navigates_exact_name_and_contact_duplicates(
    client: TestClient,
    auth_headers: dict,
    db: Session,
    test_resume: Resume,
    test_position: Position,
):
    test_resume.parse_status = "success"
    duplicate = Resume(
        id=uuid4(),
        tenant_id=test_position.tenant_id,
        candidate_name=f" {test_resume.candidate_name} ",
        contact=f" {test_resume.contact} ",
        email="new-version@example.com",
        position_id=test_position.id,
        file_path="/uploads/new-version.pdf",
        parse_status="success",
        status=ResumeStatus.PENDING_SCREENING,
    )
    same_phone_different_name = Resume(
        id=uuid4(),
        tenant_id=test_position.tenant_id,
        candidate_name="Different Candidate",
        contact=test_resume.contact,
        email="different@example.com",
        position_id=test_position.id,
        file_path="/uploads/different.pdf",
        parse_status="success",
        status=ResumeStatus.PENDING_SCREENING,
    )
    db.add_all([duplicate, same_phone_different_name])
    db.commit()

    list_response = client.get("/api/resumes", headers=auth_headers)
    assert list_response.status_code == status.HTTP_200_OK
    rows = {item["id"]: item for item in list_response.json()}
    assert rows[str(test_resume.id)]["duplicate_resume_count"] == 2
    assert rows[str(duplicate.id)]["duplicate_resume_count"] == 2
    assert rows[str(same_phone_different_name.id)]["duplicate_resume_count"] == 1

    duplicates_response = client.get(
        f"/api/resumes/{test_resume.id}/duplicates",
        headers=auth_headers,
    )
    assert duplicates_response.status_code == status.HTTP_200_OK
    assert [item["id"] for item in duplicates_response.json()] == [
        str(duplicate.id)
    ]


def test_does_not_group_unparsed_or_differently_formatted_contacts(
    client: TestClient,
    auth_headers: dict,
    db: Session,
    test_resume: Resume,
    test_position: Position,
):
    test_resume.parse_status = "success"
    db.add_all([
        Resume(
            id=uuid4(),
            tenant_id=test_position.tenant_id,
            candidate_name=test_resume.candidate_name,
            contact=f"+86 {test_resume.contact}",
            position_id=test_position.id,
            file_path="/uploads/formatted.pdf",
            parse_status="success",
            status=ResumeStatus.PENDING_SCREENING,
        ),
        Resume(
            id=uuid4(),
            tenant_id=test_position.tenant_id,
            candidate_name=test_resume.candidate_name,
            contact=test_resume.contact,
            position_id=test_position.id,
            file_path="/uploads/processing.pdf",
            parse_status="processing",
            status=ResumeStatus.PENDING_SCREENING,
        ),
    ])
    db.commit()

    response = client.get("/api/resumes", headers=auth_headers)
    assert response.status_code == status.HTTP_200_OK
    rows = {item["id"]: item for item in response.json()}
    assert rows[str(test_resume.id)]["duplicate_resume_count"] == 1
    assert all(item["duplicate_resume_count"] == 1 for item in rows.values())
