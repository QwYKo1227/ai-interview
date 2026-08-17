from uuid import UUID, uuid4

from fastapi import status
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.models.models import (
    Position,
    PositionCategory,
    PositionEvent,
    PositionEventType,
    PositionStatus,
    Resume,
    ResumeStatus,
    User,
    UserRole,
)
from app.services.position_service import get_position_events


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


class TestPositionLifecycleAudit:
    def test_creation_records_initial_status_and_owner_events(
        self, client: TestClient, auth_headers: dict, db: Session
    ):
        created = client.post(
            "/api/positions",
            headers=auth_headers,
            json={"title": "Audit Position", "description": "Audit"},
        )

        assert created.status_code == status.HTTP_200_OK
        events = db.query(PositionEvent).filter(
            PositionEvent.position_id == UUID(created.json()["id"])
        ).all()
        assert {event.event_type for event in events} == {
            PositionEventType.INITIAL_STATUS,
            PositionEventType.INITIAL_OWNER,
        }

    def test_events_resolve_legacy_initial_owner_id_to_name(
        self, db: Session, test_user: User
    ):
        position = create_position(db, "Legacy Owner Baseline", test_user)
        db.add(PositionEvent(
            tenant_id=position.tenant_id,
            position_id=position.id,
            event_type=PositionEventType.INITIAL_OWNER,
            new_value=str(test_user.id),
            reason="历史负责人基线",
            event_metadata={"backfilled": True},
        ))
        db.commit()

        initial_owner = get_position_events(db, position.id)[0]

        assert initial_owner.event_metadata["new_owner_name"] == (
            test_user.full_name or test_user.email
        )

    def test_pause_requires_reason_and_records_server_timestamp(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        position = create_position(
            db, "Published", test_user, PositionStatus.PUBLISHED
        )

        rejected = client.put(
            f"/api/positions/{position.id}",
            headers=auth_headers,
            json={"status": "paused"},
        )
        assert rejected.status_code == status.HTTP_400_BAD_REQUEST

        changed = client.put(
            f"/api/positions/{position.id}",
            headers=auth_headers,
            json={"status": "paused", "status_change_reason": "等待预算确认"},
        )
        assert changed.status_code == status.HTTP_200_OK
        assert changed.json()["status"] == "paused"
        event = db.query(PositionEvent).filter(
            PositionEvent.position_id == position.id,
            PositionEvent.event_type == PositionEventType.STATUS_CHANGED,
        ).one()
        assert (event.old_value, event.new_value) == ("published", "paused")
        assert event.reason == "等待预算确认"
        assert event.occurred_at is not None

    def test_batch_status_is_atomic_when_any_transition_is_invalid(
        self, client: TestClient, auth_headers: dict, db: Session, test_user: User
    ):
        published = create_position(
            db, "Published Batch", test_user, PositionStatus.PUBLISHED
        )
        draft = create_position(db, "Draft Batch", test_user, PositionStatus.OPEN)

        response = client.post(
            "/api/positions/batch-status",
            headers=auth_headers,
            json={
                "position_ids": [str(published.id), str(draft.id)],
                "status": "paused",
                "reason": "统一暂停",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        db.expire_all()
        assert db.get(Position, published.id).status == PositionStatus.PUBLISHED
        assert db.get(Position, draft.id).status == PositionStatus.OPEN

    def test_admin_owner_and_status_change_create_two_events_at_same_time(
        self,
        client: TestClient,
        admin_auth_headers: dict,
        db: Session,
        test_user: User,
    ):
        new_owner = create_manager(
            db, "new-owner@example.com", "New Owner", test_user.tenant_id
        )
        position = create_position(
            db, "Combined Change", test_user, PositionStatus.PUBLISHED
        )

        response = client.put(
            f"/api/positions/{position.id}",
            headers=admin_auth_headers,
            json={
                "status": "paused",
                "status_change_reason": "项目调整",
                "hiring_manager_id": str(new_owner.id),
                "owner_change_reason": "招聘分工调整",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        events = db.query(PositionEvent).filter(
            PositionEvent.position_id == position.id,
            PositionEvent.event_type.in_([
                PositionEventType.STATUS_CHANGED,
                PositionEventType.OWNER_CHANGED,
            ]),
        ).all()
        assert len(events) == 2
        assert events[0].occurred_at == events[1].occurred_at
        assert {event.reason for event in events} == {"项目调整", "招聘分工调整"}

    def test_admin_soft_delete_and_restore_are_audited(
        self,
        client: TestClient,
        auth_headers: dict,
        admin_auth_headers: dict,
        db: Session,
        test_user: User,
    ):
        position = create_position(db, "Deletable", test_user)

        deleted = client.delete(
            f"/api/positions/{position.id}",
            headers=admin_auth_headers,
            params={"reason": "重复岗位"},
        )
        assert deleted.status_code == status.HTTP_200_OK
        assert client.get(
            f"/api/positions/{position.id}", headers=auth_headers
        ).status_code == status.HTTP_404_NOT_FOUND
        admin_list = client.get(
            "/api/positions",
            headers=admin_auth_headers,
            params={"deleted_only": True},
        ).json()
        assert [item["id"] for item in admin_list] == [str(position.id)]
        assert admin_list[0]["deleted_at"]

        restored = client.post(
            f"/api/positions/{position.id}/restore",
            headers=admin_auth_headers,
            json={"reason": "确认继续招聘"},
        )
        assert restored.status_code == status.HTTP_200_OK
        assert restored.json()["status"] == "open"
        assert client.get(
            "/api/positions", headers=auth_headers
        ).status_code == status.HTTP_200_OK
        events = db.query(PositionEvent).filter(
            PositionEvent.position_id == position.id
        ).all()
        assert {event.event_type for event in events} >= {
            PositionEventType.SOFT_DELETED,
            PositionEventType.RESTORED,
        }

class TestPositionPriorityAndCategoryFilterCompatibility:
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
