from uuid import UUID

from sqlalchemy.orm import Session

from app.models.models import User, UserRole
from app.schemas.recruitment_performance import (
    PerformanceLeaderboard,
    PerformanceLeaderboardEntry,
    PerformanceOverview,
)
from app.services.recruitment_performance_service import calculate_overview


def build_leaderboard(
    overview: PerformanceOverview,
    *,
    current_user_id: UUID,
    eligible_user_ids: set[UUID],
) -> PerformanceLeaderboard:
    people = [
        person
        for person in overview.people
        if person.user_id in eligible_user_ids
        and person.task_points > 0
        and person.achievement_rate is not None
    ]
    people.sort(
        key=lambda person: (
            -person.achievement_rate,
            -person.score,
            -person.onboarded_count,
            person.name.casefold(),
            str(person.user_id),
        )
    )
    return PerformanceLeaderboard(
        period=overview.period,
        as_of=overview.as_of,
        status=overview.status,
        settlement_version=overview.settlement_version,
        entries=[
            PerformanceLeaderboardEntry(
                rank=index,
                name=person.name,
                achievement_rate=person.achievement_rate,
                is_current_user=person.user_id == current_user_id,
            )
            for index, person in enumerate(people, start=1)
        ],
    )


def calculate_leaderboard(
    db: Session,
    period: str,
    *,
    current_user: User,
) -> PerformanceLeaderboard:
    overview = calculate_overview(db, period)
    overview_user_ids = [person.user_id for person in overview.people]
    eligible_user_ids = {
        user_id
        for (user_id,) in db.query(User.id).filter(
            User.id.in_(overview_user_ids),
            User.role.in_([UserRole.HR, UserRole.ADMIN]),
        ).all()
    }
    return build_leaderboard(
        overview,
        current_user_id=current_user.id,
        eligible_user_ids=eligible_user_ids,
    )
