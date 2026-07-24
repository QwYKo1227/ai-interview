"""align resume status labels with the runtime model

Revision ID: q6r7s8t9u0v1
Revises: p5q6r7s8t9u0
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op


revision: str = "q6r7s8t9u0v1"
down_revision: Union[str, None] = "p5q6r7s8t9u0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RESUME_STATUS_VALUES = (
    "PENDING_SCREENING",
    "PENDING_REVIEW",
    "PENDING_DEPT_REVIEW",
    "PENDING_HR_DECISION",
    "AUTO_REJECTED_PENDING_REVIEW",
    "PENDING_INTERVIEW",
    "INTERVIEW_PASSED",
    "INTERVIEW_FAILED",
    "OFFER_PENDING",
    "OFFER_ACCEPTED",
    "OFFER_REJECTED",
    "ONBOARDING",
    "COMPLETED",
    "REJECTED",
    "WAITLIST",
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE resumes ALTER COLUMN status TYPE varchar "
        "USING upper(status::text)"
    )
    op.execute("DROP TYPE resumestatus")
    labels = ", ".join(f"'{value}'" for value in RESUME_STATUS_VALUES)
    op.execute(f"CREATE TYPE resumestatus AS ENUM ({labels})")
    op.execute(
        "ALTER TABLE resumes ALTER COLUMN status TYPE resumestatus "
        "USING status::resumestatus"
    )


def downgrade() -> None:
    # Retain the corrected labels.  Reintroducing the historical mixed-case
    # type would make existing application queries fail and risks data loss.
    pass
