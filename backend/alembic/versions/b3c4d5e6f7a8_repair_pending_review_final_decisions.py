"""repair final interview decisions left at pending review

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
"""

from alembic import op
import sqlalchemy as sa


revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def _set_tenant(connection, tenant_id) -> None:
    connection.execute(
        sa.text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


def _repair_tenant_final_decisions(connection) -> None:
    connection.execute(
        sa.text(
            """
            WITH latest_decision AS (
                SELECT DISTINCT ON (tenant_id, resume_id)
                    tenant_id,
                    id AS interview_id,
                    resume_id,
                    result::text AS result,
                    final_decision_by,
                    final_decision_at
                FROM interviews
                WHERE final_decision_at IS NOT NULL
                ORDER BY
                    tenant_id,
                    resume_id,
                    round DESC,
                    final_decision_at DESC,
                    created_at DESC,
                    id DESC
            ), repaired AS (
                UPDATE resumes AS resume
                SET status = CASE
                        WHEN decision.result IN ('passed', 'hired')
                            THEN 'INTERVIEW_PASSED'
                        WHEN decision.result = 'rejected'
                            THEN 'INTERVIEW_FAILED'
                        WHEN decision.result = 'next_round'
                            THEN 'PENDING_NEXT_INTERVIEW'
                        ELSE resume.status
                    END,
                    screening_result = CASE
                        WHEN decision.result IN ('passed', 'hired', 'next_round')
                            THEN 'PASSED'::screeningresult
                        WHEN decision.result = 'rejected'
                            THEN 'REJECTED'::screeningresult
                        ELSE resume.screening_result
                    END
                FROM latest_decision AS decision
                WHERE resume.tenant_id = decision.tenant_id
                  AND resume.id = decision.resume_id
                  AND resume.status = 'PENDING_REVIEW'
                  AND decision.result IN (
                      'passed', 'hired', 'rejected', 'next_round'
                  )
                RETURNING
                    resume.tenant_id,
                    resume.id AS resume_id,
                    resume.status::text AS new_status,
                    decision.interview_id,
                    decision.final_decision_by,
                    decision.final_decision_at
            )
            INSERT INTO resume_status_events (
                id,
                tenant_id,
                resume_id,
                old_status,
                new_status,
                source,
                source_id,
                actor_id,
                reason,
                occurred_at
            )
            SELECT
                gen_random_uuid(),
                tenant_id,
                resume_id,
                'pending_review',
                lower(new_status),
                'interview_backfill',
                interview_id,
                final_decision_by,
                'Repair final interview decision skipped from pending_review',
                final_decision_at
            FROM repaired
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
        _repair_tenant_final_decisions(connection)
    connection.execute(
        sa.text("SELECT set_config('app.current_tenant_id', '', true)")
    )


def downgrade() -> None:
    # The invalid pre-decision status cannot be reconstructed safely.
    pass
