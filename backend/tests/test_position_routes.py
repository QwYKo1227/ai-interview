from uuid import uuid4

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.models.models import (
    Position,
    PositionStatus,
    PositionUrgency,
    User,
    UserRole,
)


def create_manager(db: Session, email: str, full_name: str) -> User:
    manager = User(
        id=uuid4(),
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
    urgency: PositionUrgency = PositionUrgency.MEDIUM,
) -> Position:
    position = Position(
        id=uuid4(),
        title=title,
        description=f"{title} description",
        status=position_status,
        department=department,
        urgency=urgency,
        hiring_manager_id=manager.id,
    )
    db.add(position)
    db.commit()
    db.refresh(position)
    return position


class TestPositionHiringManagerFilter:
    def test_omitting_manager_returns_positions_for_all_managers(
        self, client: TestClient, auth_headers: dict, db: Session
    ):
        first = create_manager(db, "first@example.com", "First Manager")
        second = create_manager(db, "second@example.com", "Second Manager")
        create_position(db, "Backend Engineer", first)
        create_position(db, "Frontend Engineer", second)

        response = client.get("/api/positions", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert {item["title"] for item in response.json()} == {
            "Backend Engineer",
            "Frontend Engineer",
        }

    def test_manager_filter_combines_with_title_and_status(
        self, client: TestClient, auth_headers: dict, db: Session
    ):
        target = create_manager(db, "target@example.com", "Target Manager")
        other = create_manager(db, "other@example.com", "Other Manager")
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
    def test_returns_distinct_managers_with_positions(
        self, client: TestClient, auth_headers: dict, db: Session
    ):
        assigned = create_manager(db, "assigned@example.com", "Assigned Manager")
        create_manager(db, "unused@example.com", "Unused Manager")
        create_position(db, "Backend Engineer", assigned)
        create_position(db, "Frontend Engineer", assigned)

        response = client.get(
            "/api/positions/hiring-managers", headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [
            {
                "id": str(assigned.id),
                "full_name": "Assigned Manager",
                "email": "assigned@example.com",
            }
        ]

    def test_requires_authentication(self, client: TestClient):
        response = client.get("/api/positions/hiring-managers")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestPositionDepartmentAndUrgencyFilters:
    def test_combines_department_urgency_manager_status_and_title(
        self, client: TestClient, auth_headers: dict, db: Session
    ):
        target = create_manager(db, "target-filter@example.com", "Target Filter")
        other = create_manager(db, "other-filter@example.com", "Other Filter")
        create_position(
            db,
            "Senior Backend Engineer",
            target,
            PositionStatus.PUBLISHED,
            "Engineering",
            PositionUrgency.URGENT,
        )
        create_position(
            db,
            "Senior Backend Engineer",
            target,
            PositionStatus.PUBLISHED,
            "Engineering",
            PositionUrgency.LOW,
        )
        create_position(
            db,
            "Senior Backend Engineer",
            target,
            PositionStatus.PUBLISHED,
            "People",
            PositionUrgency.URGENT,
        )
        create_position(
            db,
            "Senior Backend Engineer",
            other,
            PositionStatus.PUBLISHED,
            "Engineering",
            PositionUrgency.URGENT,
        )

        response = client.get(
            "/api/positions",
            params={
                "title": "Senior",
                "department": "Engineering",
                "urgency": "urgent",
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


class TestPositionDepartmentOptions:
    def test_returns_distinct_non_empty_sorted_departments(
        self, client: TestClient, auth_headers: dict, db: Session
    ):
        manager = create_manager(db, "departments@example.com", "Department Owner")
        create_position(db, "Platform", manager, department="Engineering")
        create_position(db, "Frontend", manager, department="Engineering")
        create_position(db, "Recruiter", manager, department="People")
        create_position(db, "Unassigned Department", manager, department=None)

        response = client.get("/api/positions/departments", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == ["Engineering", "People"]

    def test_requires_authentication(self, client: TestClient):
        response = client.get("/api/positions/departments")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
