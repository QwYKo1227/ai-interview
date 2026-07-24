"""align interview enum values with the runtime model

Revision ID: o4p5q6r7s8t9
Revises: n3o4p5q6r7s8
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op


revision: str = "o4p5q6r7s8t9"
down_revision: Union[str, None] = "n3o4p5q6r7s8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _replace_enum(type_name: str, column_name: str, values: tuple[str, ...]) -> None:
    op.execute(
        f"ALTER TABLE interviews ALTER COLUMN {column_name} TYPE varchar "
        f"USING lower({column_name}::text)"
    )
    op.execute(f"DROP TYPE {type_name}")
    labels = ", ".join(f"'{value}'" for value in values)
    op.execute(f"CREATE TYPE {type_name} AS ENUM ({labels})")
    op.execute(
        f"ALTER TABLE interviews ALTER COLUMN {column_name} TYPE {type_name} "
        f"USING {column_name}::{type_name}"
    )


def upgrade() -> None:
    _replace_enum(
        "interviewresult",
        "result",
        ("pending", "passed", "rejected", "waitlist", "hired", "next_round"),
    )
    _replace_enum(
        "interviewstatus",
        "status",
        ("scheduled", "in_progress", "analyzing", "completed", "cancelled"),
    )


def downgrade() -> None:
    # Preserve every value introduced by the current model while restoring the
    # legacy label casing.  No interview row is deleted during rollback.
    op.execute(
        "ALTER TABLE interviews ALTER COLUMN result TYPE varchar "
        "USING upper(result::text)"
    )
    op.execute("DROP TYPE interviewresult")
    op.execute(
        "CREATE TYPE interviewresult AS ENUM "
        "('PENDING', 'PASSED', 'REJECTED', 'WAITLIST', 'HIRED', 'NEXT_ROUND')"
    )
    op.execute(
        "ALTER TABLE interviews ALTER COLUMN result TYPE interviewresult "
        "USING result::interviewresult"
    )

    op.execute(
        "ALTER TABLE interviews ALTER COLUMN status TYPE varchar USING "
        "CASE status::text "
        "WHEN 'scheduled' THEN 'SCHEDULED' "
        "WHEN 'completed' THEN 'COMPLETED' "
        "WHEN 'cancelled' THEN 'CANCELLED' "
        "ELSE status::text END"
    )
    op.execute("DROP TYPE interviewstatus")
    op.execute(
        "CREATE TYPE interviewstatus AS ENUM "
        "('SCHEDULED', 'COMPLETED', 'CANCELLED', 'in_progress', 'analyzing')"
    )
    op.execute(
        "ALTER TABLE interviews ALTER COLUMN status TYPE interviewstatus "
        "USING status::interviewstatus"
    )
