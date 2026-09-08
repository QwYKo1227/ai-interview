"""backfill departed HC rounds through forced tenant RLS

Revision ID: j1k2l3m4n5o6
Revises: i0j1k2l3m4n5
"""

from alembic import op


revision = "j1k2l3m4n5o6"
down_revision = "i0j1k2l3m4n5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE "offers" DISABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "recruitment_hc_slots" DISABLE ROW LEVEL SECURITY')

    op.execute("""
        INSERT INTO recruitment_hc_slots (
            id, tenant_id, position_id, slot_number, status,
            assigned_at, round_started_at, accepted_at, completed_at,
            candidate_resume_id, recruitment_round, status_reason, created_at
        )
        SELECT
            gen_random_uuid(), offer.tenant_id, offer.position_id,
            current_slot.slot_number, 'released', current_slot.assigned_at,
            current_slot.assigned_at, offer.accepted_at, offer.actual_onboarded_at,
            offer.resume_id, current_slot.recruitment_round - 1,
            '员工离职，HC已释放，历史积分已冻结', current_slot.created_at
        FROM offers AS offer
        JOIN LATERAL (
            SELECT slot.*
            FROM recruitment_hc_slots AS slot
            WHERE slot.tenant_id = offer.tenant_id
              AND slot.position_id = offer.position_id
              AND slot.candidate_resume_id IS NULL
              AND slot.recruitment_round > 1
              AND slot.round_started_at = offer.departed_at
            ORDER BY slot.recruitment_round DESC
            LIMIT 1
        ) AS current_slot ON TRUE
        WHERE offer.departure_released_hc IS TRUE
          AND offer.departed_at IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM recruitment_hc_slots AS historical
              WHERE historical.tenant_id = offer.tenant_id
                AND historical.position_id = offer.position_id
                AND historical.slot_number = current_slot.slot_number
                AND historical.recruitment_round = current_slot.recruitment_round - 1
          )
    """)
    op.execute("""
        UPDATE recruitment_hc_slots AS slot
        SET assigned_at = offer.departed_at,
            status_reason = 'HC释放后开启新一轮招聘'
        FROM offers AS offer
        WHERE offer.departure_released_hc IS TRUE
          AND offer.departed_at IS NOT NULL
          AND slot.tenant_id = offer.tenant_id
          AND slot.position_id = offer.position_id
          AND slot.candidate_resume_id IS NULL
          AND slot.recruitment_round > 1
          AND slot.round_started_at = offer.departed_at
    """)
    op.execute("""
        UPDATE recruitment_hc_slots AS slot
        SET status = 'departed_retained',
            status_reason = '员工离职，HC未释放，历史积分已冻结'
        FROM offers AS offer
        WHERE offer.departure_released_hc IS FALSE
          AND offer.departed_at IS NOT NULL
          AND slot.tenant_id = offer.tenant_id
          AND slot.position_id = offer.position_id
          AND slot.candidate_resume_id = offer.resume_id
    """)

    op.execute('ALTER TABLE "offers" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "offers" FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "recruitment_hc_slots" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "recruitment_hc_slots" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    # The preceding schema migration owns the reversible representation change.
    pass
