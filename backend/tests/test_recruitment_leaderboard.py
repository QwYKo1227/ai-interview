from uuid import uuid4

from app.schemas.recruitment_performance import PerformanceOverview, PersonScore
from app.services.recruitment_leaderboard_service import build_leaderboard


def make_person(
    name: str,
    rate: float | None,
    *,
    score: float = 10,
    onboarded_count: int = 0,
    task_points: float = 10,
) -> PersonScore:
    return PersonScore(
        user_id=uuid4(),
        name=name,
        email=f"{uuid4()}@example.com",
        hc_count=1,
        excluded_count=0,
        onboarded_count=onboarded_count,
        task_points=task_points,
        score=score,
        achievement_rate=rate,
        positions=[],
    )


def test_hr_can_view_minimal_leaderboard(client, auth_headers, test_user, test_position):
    response = client.get(
        "/api/recruitment-performance/leaderboard?period=2026-Q3",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["entries"] == [
        {
            "rank": 1,
            "name": test_user.full_name,
            "achievement_rate": 0.0,
            "is_current_user": True,
        }
    ]


def test_interviewer_cannot_view_leaderboard(client, interviewer_auth_headers):
    response = client.get(
        "/api/recruitment-performance/leaderboard?period=2026-Q3",
        headers=interviewer_auth_headers,
    )

    assert response.status_code == 403


def test_leaderboard_uses_confirmed_tie_breakers_and_excludes_invalid_people():
    first = make_person("同名", 1.2, score=100, onboarded_count=1)
    second = make_person("同名", 1.2, score=90, onboarded_count=3)
    third = make_person("安琪", 1.2, score=90, onboarded_count=2)
    fourth = make_person("周明", 1.1, score=200, onboarded_count=5)
    no_rate = make_person("无达成率", None)
    no_task = make_person("无任务", 2.0, task_points=0)
    people = [fourth, no_rate, third, second, no_task, first]
    overview = PerformanceOverview(
        period="2026-Q3",
        as_of="2026-08-20",
        status="trial",
        people=people,
    )

    result = build_leaderboard(
        overview,
        current_user_id=third.user_id,
        eligible_user_ids={person.user_id for person in people},
    )

    assert [(entry.rank, entry.name, entry.achievement_rate) for entry in result.entries] == [
        (1, "同名", 1.2),
        (2, "同名", 1.2),
        (3, "安琪", 1.2),
        (4, "周明", 1.1),
    ]
    assert [entry.rank for entry in result.entries if entry.is_current_user] == [3]
