"""align interview decisions and resume interview-stage statuses

Revision ID: w2x3y4z5a6b7
Revises: v1w2x3y4z5a6
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "w2x3y4z5a6b7"
down_revision = "v1w2x3y4z5a6"
branch_labels = None
depends_on = None


RESUME_STATUS_VALUES = (
    "PENDING_SCREENING",
    "PENDING_REVIEW",
    "PENDING_DEPT_REVIEW",
    "PENDING_HR_DECISION",
    "AUTO_REJECTED_PENDING_REVIEW",
    "PENDING_INTERVIEW",
    "INTERVIEW_SCHEDULED",
    "INTERVIEW_IN_PROGRESS",
    "PENDING_INTERVIEW_RESULT",
    "PENDING_NEXT_INTERVIEW",
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
    op.add_column("interviews", sa.Column("decision_history", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("interviews", sa.Column("cancel_reason", sa.Text(), nullable=True))
    op.add_column("interviews", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))

    op.execute("UPDATE interviews SET result = 'pending' WHERE result::text = 'waitlist'")
    op.execute("UPDATE interviews SET result = 'passed' WHERE result::text = 'hired'")
    op.execute(
        "UPDATE interviews SET final_decision_at = COALESCE(ended_at, created_at), "
        "decision_history = jsonb_build_array(jsonb_build_object("
        "'action', 'migrated', 'result', result::text, 'at', COALESCE(ended_at, created_at))) "
        "WHERE final_decision_at IS NULL AND result::text IN ('passed', 'rejected', 'next_round')"
    )
    op.execute("UPDATE interviews SET lifecycle_state = 'cancelled' WHERE status::text = 'cancelled'")
    op.execute("UPDATE interviews SET cancel_reason = comments->>'cancel_reason' WHERE comments->>'cancel_reason' IS NOT NULL")
    op.execute("UPDATE interviews SET cancelled_at = COALESCE(ended_at, created_at) WHERE lifecycle_state = 'cancelled' AND cancelled_at IS NULL")

    op.execute("ALTER TABLE resumes ALTER COLUMN status TYPE varchar USING status::text")
    op.execute("UPDATE resumes SET status = 'OFFER_ACCEPTED' WHERE status = 'ONBOARDING'")
    op.execute("DROP TYPE resumestatus")
    labels = ", ".join(f"'{value}'" for value in RESUME_STATUS_VALUES)
    op.execute(f"CREATE TYPE resumestatus AS ENUM ({labels})")

    op.execute(
        """
        WITH latest AS (
            SELECT DISTINCT ON (resume_id)
                id, resume_id, lifecycle_state, status::text AS interview_status,
                result::text AS result, final_decision_at
            FROM interviews
            ORDER BY resume_id, round DESC, created_at DESC, id DESC
        ), resolved AS (
            SELECT latest.*,
                (
                    SELECT previous.result::text
                    FROM interviews previous
                    WHERE previous.resume_id = latest.resume_id
                      AND previous.id <> latest.id
                      AND previous.final_decision_at IS NOT NULL
                    ORDER BY previous.round DESC, previous.created_at DESC, previous.id DESC
                    LIMIT 1
                ) AS previous_result
            FROM latest
        )
        UPDATE resumes
        SET status = CASE
            WHEN resolved.final_decision_at IS NOT NULL AND resolved.result = 'next_round' THEN 'PENDING_NEXT_INTERVIEW'
            WHEN resolved.final_decision_at IS NOT NULL AND resolved.result = 'passed' THEN 'INTERVIEW_PASSED'
            WHEN resolved.final_decision_at IS NOT NULL AND resolved.result = 'rejected' THEN 'INTERVIEW_FAILED'
            WHEN resolved.lifecycle_state = 'cancelled' AND resolved.previous_result = 'next_round' THEN 'PENDING_NEXT_INTERVIEW'
            WHEN resolved.lifecycle_state = 'cancelled' THEN 'PENDING_INTERVIEW'
            WHEN resolved.lifecycle_state = 'scheduled' THEN 'INTERVIEW_SCHEDULED'
            WHEN resolved.lifecycle_state = 'in_progress' THEN 'INTERVIEW_IN_PROGRESS'
            WHEN resolved.lifecycle_state IN ('ending', 'ended') THEN 'PENDING_INTERVIEW_RESULT'
            ELSE resumes.status
        END
        FROM resolved
        WHERE resumes.id = resolved.resume_id
          AND resumes.status IN ('PENDING_INTERVIEW', 'INTERVIEW_PASSED', 'INTERVIEW_FAILED')
        """
    )
    op.execute(
        "ALTER TABLE resumes ALTER COLUMN status TYPE resumestatus "
        "USING status::resumestatus"
    )
    op.execute(
        """
        WITH latest AS (
            SELECT DISTINCT ON (resume_id) resume_id, result::text AS result, final_decision_at
            FROM interviews
            ORDER BY resume_id, round DESC, created_at DESC, id DESC
        )
        UPDATE resumes
        SET screening_result = CASE
            WHEN latest.result IN ('passed', 'next_round') THEN 'PASSED'::screeningresult
            WHEN latest.result = 'rejected' THEN 'REJECTED'::screeningresult
            ELSE resumes.screening_result
        END
        FROM latest
        WHERE resumes.id = latest.resume_id AND latest.final_decision_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE resumes ALTER COLUMN status TYPE varchar USING status::text")
    op.execute("UPDATE resumes SET status = 'PENDING_INTERVIEW' WHERE status IN ('INTERVIEW_SCHEDULED', 'INTERVIEW_IN_PROGRESS', 'PENDING_INTERVIEW_RESULT', 'PENDING_NEXT_INTERVIEW')")
    op.execute("DROP TYPE resumestatus")
    old_values = tuple(value for value in RESUME_STATUS_VALUES if value not in {
        "INTERVIEW_SCHEDULED", "INTERVIEW_IN_PROGRESS", "PENDING_INTERVIEW_RESULT", "PENDING_NEXT_INTERVIEW"
    })
    labels = ", ".join(f"'{value}'" for value in old_values)
    op.execute(f"CREATE TYPE resumestatus AS ENUM ({labels})")
    op.execute("ALTER TABLE resumes ALTER COLUMN status TYPE resumestatus USING status::resumestatus")
    op.drop_column("interviews", "cancelled_at")
    op.drop_column("interviews", "cancel_reason")
    op.drop_column("interviews", "decision_history")
