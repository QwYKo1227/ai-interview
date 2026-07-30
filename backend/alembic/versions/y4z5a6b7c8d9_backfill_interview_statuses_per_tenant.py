"""backfill interview and resume statuses within each tenant

Revision ID: y4z5a6b7c8d9
Revises: x3y4z5a6b7c8
"""

from alembic import op
import sqlalchemy as sa


revision = "y4z5a6b7c8d9"
down_revision = "x3y4z5a6b7c8"
branch_labels = None
depends_on = None


def _set_tenant(connection, tenant_id) -> None:
    connection.execute(
        sa.text(
            "SELECT set_config("
            "'app.current_tenant_id', :tenant_id, true"
            ")"
        ),
        {"tenant_id": str(tenant_id)},
    )


def _repair_tenant_statuses(connection) -> None:
    connection.execute(
        sa.text(
            """
            UPDATE interviews
            SET lifecycle_state = CASE
                WHEN status::text = 'in_progress' THEN 'in_progress'
                WHEN status::text IN ('analyzing', 'completed') THEN 'ended'
                WHEN status::text = 'cancelled' THEN 'cancelled'
                ELSE lifecycle_state
            END
            WHERE lifecycle_state = 'scheduled'
              AND status::text IN (
                  'in_progress', 'analyzing', 'completed', 'cancelled'
              )
            """
        )
    )
    connection.execute(
        sa.text(
            "UPDATE interviews SET result = 'pending' "
            "WHERE result::text = 'waitlist'"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE interviews SET result = 'passed' "
            "WHERE result::text = 'hired'"
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE interviews
            SET final_decision_at = COALESCE(ended_at, created_at),
                decision_history = jsonb_build_array(
                    jsonb_build_object(
                        'action', 'migrated',
                        'result', result::text,
                        'at', COALESCE(ended_at, created_at)
                    )
                )
            WHERE final_decision_at IS NULL
              AND result::text IN ('passed', 'rejected', 'next_round')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE interviews
            SET cancel_reason = comments->>'cancel_reason'
            WHERE cancel_reason IS NULL
              AND comments->>'cancel_reason' IS NOT NULL
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE interviews
            SET cancelled_at = COALESCE(ended_at, created_at)
            WHERE lifecycle_state = 'cancelled'
              AND cancelled_at IS NULL
            """
        )
    )
    connection.execute(
        sa.text(
            """
            WITH latest AS (
                SELECT DISTINCT ON (tenant_id, resume_id)
                    tenant_id,
                    id,
                    resume_id,
                    lifecycle_state,
                    result::text AS result,
                    final_decision_at
                FROM interviews
                ORDER BY
                    tenant_id,
                    resume_id,
                    round DESC,
                    created_at DESC,
                    id DESC
            ), resolved AS (
                SELECT latest.*,
                    (
                        SELECT previous.result::text
                        FROM interviews previous
                        WHERE previous.tenant_id = latest.tenant_id
                          AND previous.resume_id = latest.resume_id
                          AND previous.id <> latest.id
                          AND previous.final_decision_at IS NOT NULL
                        ORDER BY
                            previous.round DESC,
                            previous.created_at DESC,
                            previous.id DESC
                        LIMIT 1
                    ) AS previous_result
                FROM latest
            )
            UPDATE resumes
            SET status = CASE
                WHEN resolved.final_decision_at IS NOT NULL
                     AND resolved.result = 'next_round'
                    THEN 'PENDING_NEXT_INTERVIEW'
                WHEN resolved.final_decision_at IS NOT NULL
                     AND resolved.result = 'passed'
                    THEN 'INTERVIEW_PASSED'
                WHEN resolved.final_decision_at IS NOT NULL
                     AND resolved.result = 'rejected'
                    THEN 'INTERVIEW_FAILED'
                WHEN resolved.lifecycle_state = 'cancelled'
                     AND resolved.previous_result = 'next_round'
                    THEN 'PENDING_NEXT_INTERVIEW'
                WHEN resolved.lifecycle_state = 'cancelled'
                    THEN 'PENDING_INTERVIEW'
                WHEN resolved.lifecycle_state = 'scheduled'
                    THEN 'INTERVIEW_SCHEDULED'
                WHEN resolved.lifecycle_state = 'in_progress'
                    THEN 'INTERVIEW_IN_PROGRESS'
                WHEN resolved.lifecycle_state IN ('ending', 'ended')
                    THEN 'PENDING_INTERVIEW_RESULT'
                ELSE resumes.status
            END
            FROM resolved
            WHERE resumes.tenant_id = resolved.tenant_id
              AND resumes.id = resolved.resume_id
              AND resumes.status IN (
                  'PENDING_INTERVIEW',
                  'INTERVIEW_SCHEDULED',
                  'INTERVIEW_IN_PROGRESS',
                  'PENDING_INTERVIEW_RESULT',
                  'PENDING_NEXT_INTERVIEW',
                  'INTERVIEW_PASSED',
                  'INTERVIEW_FAILED'
              )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            WITH latest AS (
                SELECT DISTINCT ON (tenant_id, resume_id)
                    tenant_id,
                    resume_id,
                    result::text AS result,
                    final_decision_at
                FROM interviews
                ORDER BY
                    tenant_id,
                    resume_id,
                    round DESC,
                    created_at DESC,
                    id DESC
            )
            UPDATE resumes
            SET screening_result = CASE
                WHEN latest.result IN ('passed', 'next_round')
                    THEN 'PASSED'::screeningresult
                WHEN latest.result = 'rejected'
                    THEN 'REJECTED'::screeningresult
                ELSE resumes.screening_result
            END
            FROM latest
            WHERE resumes.tenant_id = latest.tenant_id
              AND resumes.id = latest.resume_id
              AND latest.final_decision_at IS NOT NULL
            """
        )
    )


def upgrade() -> None:
    connection = op.get_bind()
    tenant_ids = connection.execute(
        sa.text("SELECT id FROM tenants ORDER BY id")
    ).scalars()
    for tenant_id in tenant_ids:
        _set_tenant(connection, tenant_id)
        _repair_tenant_statuses(connection)
    connection.execute(
        sa.text(
            "SELECT set_config('app.current_tenant_id', '', true)"
        )
    )


def downgrade() -> None:
    # The original status values cannot be reconstructed after later workflow
    # actions. Keep the repaired, application-consistent state.
    pass
