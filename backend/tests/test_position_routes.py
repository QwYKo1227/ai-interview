from uuid import uuid4

from fastapi import status
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.models.models import (
    Position,
    PositionCategory,
    PositionStatus,
    Resume,
    ResumeStatus,
    User,
    UserRole,
)


def create_manager(
    db: Session, email: str, full_name: str, tenant_id
) -> User:
    manager = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email=email,
        full_name=full_name,
        hashed_password=get_password_hash("testpassword"),
        role=UserRole.HR,
        is_active=True,
    )
    db.add(manager)
    db.commit()
    db.refresh(manager)
    return manager


def create_position(
    db: Session,
    title: str,
    manager: User,
    position_status: PositionStatus = PositionStatus.OPEN,
    department: str | None = None,
    priority: int = 3,
    category: PositionCategory = PositionCategory.UNCATEGORIZED,
) -> Position:
    position = Position(
        id=uuid4(),
        tenant_id=manager.tenant_id,
        title=title,
        description=f"{title} description",
        status=position_status,
        department=department,
        priority=priority,
        category=category,
        hiring_manager_id=manager.id,
    )
    db.add(position)
    db.commit()
    db.refresh(position)
    return position


def create_resume(db: Session, position: Position, status: ResumeStatus) -> Resume:
    resume = Resume(
        id=uuid4(),
        tenant_id=position.tenant_id,
        candidate_name=f"Candidate {status.value}",
        position_id=position.id,
        status=status,
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return resume


class TestPositionRecruitmentProgress:
    def test_every_resume_status_has_one_visible_progress_bucket(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        position = create_position(db, "Complete Pipeline", test_user)
        for resume_status in ResumeStatus:
            create_resume(db, position, resume_status)

        response = client.get("/api/positions", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        progress = next(
            item["stats"]
            for item in response.json()
            if item["id"] == str(position.id)
        )
        assert progress["total_resumes"] == len(ResumeStatus)
        assert progress["pending_screening"] == 6
        assert progress["pending_interview"] == 4
        assert progress["interview_completed"] == 1
        assert progress["interview_passed"] == 1
        assert progress["offer_pending"] == 1
        assert progress["offer_accepted"] == 3
        assert progress["rejected"] == 3
        assert "waitlisted" not in progress
        assert sum(
            count
            for name, count in progress.items()
            if name != "total_resumes"
        ) == progress["total_resumes"]


class TestPositionHiringManagerFilter:
    def test_omitting_manager_returns_only_current_recruiters_positions(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        first = test_user
        second = create_manager(db, "second@example.com", "Second Manager", test_user.tenant_id)
        create_position(db, "Backend Engineer", first)
        create_position(db, "Frontend Engineer", second)

        response = client.get("/api/positions", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert {item["title"] for item in response.json()} == {"Backend Engineer"}

    def test_manager_filter_combines_with_title_and_status(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        target = test_user
        other = create_manager(db, "other@example.com", "Other Manager", test_user.tenant_id)
        create_position(db, "Senior Backend Engineer", target, PositionStatus.PUBLISHED)
        create_position(db, "Backend Intern", target, PositionStatus.OPEN)
        create_position(db, "Senior Backend Engineer", other, PositionStatus.PUBLISHED)

        response = client.get(
            "/api/positions",
            params={
                "hiring_manager_id": str(target.id),
                "title": "Senior",
                "status": "published",
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert [item["title"] for item in response.json()] == [
            "Senior Backend Engineer"
        ]
        assert response.json()[0]["hiring_manager_id"] == str(target.id)


class TestHiringManagerOptions:
    def test_hr_only_receives_self_as_manager_option(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        assigned = create_manager(db, "assigned@example.com", "Assigned Manager", test_user.tenant_id)
        create_manager(db, "unused@example.com", "Unused Manager", test_user.tenant_id)
        create_position(db, "Backend Engineer", assigned)
        create_position(db, "Frontend Engineer", assigned)

        response = client.get(
            "/api/positions/hiring-managers", headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [
            {
                "id": str(test_user.id),
                "full_name": test_user.full_name,
                "email": test_user.email,
            }
        ]

    def test_requires_authentication(self, client: TestClient):
        response = client.get("/api/positions/hiring-managers")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_forbids_interviewer_access(
        self, client: TestClient, interviewer_auth_headers: dict
    ):
        response = client.get(
            "/api/positions/hiring-managers",
            headers=interviewer_auth_headers,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestPositionPriorityAndCategoryFilters:
    @pytest.mark.parametrize(
        ("urgency", "expected_priority"),
        [("low", 1), ("medium", 3), ("high", 4), ("urgent", 5)],
    )
    def test_legacy_urgency_body_maps_every_level_to_priority(
        self, client: TestClient, auth_headers: dict, urgency: str, expected_priority: int
    ):
        response = client.post(
            "/api/positions",
            headers=auth_headers,
            json={
                "title": f"Legacy {urgency}",
                "description": "Legacy priority mapping",
                "urgency": urgency,
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["priority"] == expected_priority

    def test_combines_department_priority_category_manager_status_and_title(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        target = test_user
        other = create_manager(db, "other-filter@example.com", "Other Filter", test_user.tenant_id)
        create_position(
            db,
            "Senior Backend Engineer",
            target,
            PositionStatus.PUBLISHED,
            "Engineering",
            5,
            PositionCategory.DOMESTIC_RD,
        )
        create_position(
            db,
            "Senior Backend Engineer",
            target,
            PositionStatus.PUBLISHED,
            "Engineering",
            1,
            PositionCategory.DOMESTIC_RD,
        )
        create_position(
            db,
            "Senior Backend Engineer",
            target,
            PositionStatus.PUBLISHED,
            "People",
            5,
            PositionCategory.DOMESTIC_FUNCTIONAL,
        )
        create_position(
            db,
            "Senior Backend Engineer",
            other,
            PositionStatus.PUBLISHED,
            "Engineering",
            5,
            PositionCategory.DOMESTIC_RD,
        )

        response = client.get(
            "/api/positions",
            params={
                "title": "Senior",
                "department": "Engineering",
                "priority": 5,
                "category": "domestic_rd",
                "status": "published",
                "hiring_manager_id": str(target.id),
            },
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert [item["title"] for item in response.json()] == [
            "Senior Backend Engineer"
        ]
        assert response.json()[0]["hiring_manager_id"] == str(target.id)
        assert response.json()[0]["priority"] == 5
        assert response.json()[0]["category"] == "domestic_rd"
        assert "urgency" not in response.json()[0]

    def test_legacy_urgency_query_maps_to_priority(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        create_position(db, "Urgent Position", test_user, priority=5)
        create_position(db, "Normal Position", test_user, priority=3)

        response = client.get(
            "/api/positions", params={"urgency": "urgent"}, headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert [item["title"] for item in response.json()] == ["Urgent Position"]

    def test_legacy_urgency_body_maps_to_priority_and_response_uses_new_fields(
        self, client: TestClient, auth_headers: dict
    ):
        response = client.post(
            "/api/positions",
            headers=auth_headers,
            json={
                "title": "Legacy Client Position",
                "description": "Created by an older client",
                "urgency": "high",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["priority"] == 4
        assert response.json()["category"] == "uncategorized"
        assert "urgency" not in response.json()

    def test_clearing_classification_uses_defaults(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        position = create_position(
            db,
            "Classified Position",
            test_user,
            priority=5,
            category=PositionCategory.OVERSEAS,
        )

        response = client.put(
            f"/api/positions/{position.id}",
            headers=auth_headers,
            json={"priority": None, "category": None},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["priority"] == 3
        assert response.json()["category"] == "uncategorized"


class TestPositionDepartmentOptions:
    def test_returns_distinct_non_empty_sorted_departments(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        manager = test_user
        create_position(db, "Platform", manager, department="Engineering")
        create_position(db, "Frontend", manager, department="Engineering")
        create_position(db, "Recruiter", manager, department="People")
        create_position(db, "Unassigned Department", manager, department=None)
        create_position(db, "Whitespace Department", manager, department="   ")

        response = client.get("/api/positions/departments", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == ["Engineering", "People"]

    def test_requires_authentication(self, client: TestClient):
        response = client.get("/api/positions/departments")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
