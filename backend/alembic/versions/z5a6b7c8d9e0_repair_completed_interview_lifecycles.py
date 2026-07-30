"""repair completed interview lifecycle state

Revision ID: z5a6b7c8d9e0
Revises: y4z5a6b7c8d9
"""

from alembic import op
import sqlalchemy as sa


revision = "z5a6b7c8d9e0"
down_revision = "y4z5a6b7c8d9"
branch_labels = None
depends_on = None


def _set_tenant(connection, tenant_id) -> None:
    connection.execute(
        sa.text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


def upgrade() -> None:
    connection = op.get_bind()
    tenant_ids = connection.execute(sa.text("SELECT id FROM tenants")).scalars().all()
    for tenant_id in tenant_ids:
        _set_tenant(connection, tenant_id)
        connection.execute(
            sa.text(
                """
                UPDATE interviews AS interview
                SET lifecycle_state = 'ended',
                    ended_at = COALESCE(
                        interview.ended_at,
                        (
                            SELECT MAX(panel.updated_at) AT TIME ZONE 'UTC'
                            FROM interview_panels AS panel
                            WHERE panel.tenant_id = interview.tenant_id
                              AND panel.interview_id = interview.id
                        ),
                        interview.started_at,
                        interview.created_at
                    ),
                    notes_revealed_at = COALESCE(
                        interview.notes_revealed_at,
                        interview.ended_at,
                        (
                            SELECT MAX(panel.updated_at) AT TIME ZONE 'UTC'
                            FROM interview_panels AS panel
                            WHERE panel.tenant_id = interview.tenant_id
                              AND panel.interview_id = interview.id
                        ),
                        interview.started_at,
                        interview.created_at
                    ),
                    ai_analysis_status = CASE
                        WHEN interview.status::text = 'completed'
                         AND NOT (
                            interview.recording_state = 'sealed'
                            AND COALESCE(interview.audio_records::jsonb, '{}'::jsonb)
                                ? 'full_interview'
                         )
                         AND interview.ai_analysis_status IN (
                            'pending', 'transcribing', 'analyzing'
                         )
                        THEN 'not_applicable'
                        ELSE interview.ai_analysis_status
                    END,
                    asr_job_status = CASE
                        WHEN interview.status::text = 'completed'
                         AND interview.asr_job_status = 'pending'
                         AND NOT (
                            interview.recording_state = 'sealed'
                            AND COALESCE(interview.audio_records::jsonb, '{}'::jsonb)
                                ? 'full_interview'
                         )
                        THEN 'not_applicable'
                        ELSE interview.asr_job_status
                    END,
                    asr_job_next_poll_at = CASE
                        WHEN interview.status::text = 'completed'
                         AND interview.asr_job_status = 'pending'
                         AND NOT (
                            interview.recording_state = 'sealed'
                            AND COALESCE(interview.audio_records::jsonb, '{}'::jsonb)
                                ? 'full_interview'
                         )
                        THEN NULL
                        ELSE interview.asr_job_next_poll_at
                    END
                WHERE interview.status::text IN ('analyzing', 'completed')
                  AND interview.lifecycle_state NOT IN ('ending', 'ended')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                UPDATE interview_panels AS panel
                SET notes_frozen_at = interview.ended_at
                FROM interviews AS interview
                WHERE panel.tenant_id = interview.tenant_id
                  AND panel.interview_id = interview.id
                  AND interview.lifecycle_state = 'ended'
                  AND interview.status::text IN ('analyzing', 'completed')
                  AND panel.notes_frozen_at IS NULL
                """
            )
        )
        connection.execute(
            sa.text(
                """
                UPDATE resumes AS resume
                SET status = 'PENDING_INTERVIEW_RESULT'
                FROM interviews AS interview
                WHERE resume.tenant_id = interview.tenant_id
                  AND resume.id = interview.resume_id
                  AND interview.lifecycle_state = 'ended'
                  AND interview.status::text IN ('analyzing', 'completed')
                  AND interview.final_decision_at IS NULL
                  AND resume.status IN (
                    'PENDING_INTERVIEW',
                    'INTERVIEW_SCHEDULED',
                    'INTERVIEW_IN_PROGRESS',
                    'PENDING_INTERVIEW_RESULT',
                    'PENDING_NEXT_INTERVIEW',
                    'INTERVIEW_PASSED',
                    'INTERVIEW_FAILED'
                  )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM interviews AS newer
                    WHERE newer.tenant_id = interview.tenant_id
                      AND newer.resume_id = interview.resume_id
                      AND (
                        newer.round > interview.round
                        OR (
                            newer.round = interview.round
                            AND newer.created_at > interview.created_at
                        )
                        OR (
                            newer.round = interview.round
                            AND newer.created_at = interview.created_at
                            AND newer.id > interview.id
                        )
                      )
                  )
                """
            )
        )


def downgrade() -> None:
    # This migration repairs derived lifecycle state and is intentionally
    # irreversible; restoring the invalid state would reintroduce the bug.
    pass
