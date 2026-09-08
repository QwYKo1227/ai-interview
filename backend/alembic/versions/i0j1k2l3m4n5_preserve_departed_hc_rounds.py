"""preserve departed HC rounds

Revision ID: i0j1k2l3m4n5
Revises: h9i0j1k2l3m4
"""

import uuid

import sqlalchemy as sa
from alembic import op


revision = "i0j1k2l3m4n5"
down_revision = "h9i0j1k2l3m4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_recruitment_hc_slot_number",
        "recruitment_hc_slots",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_recruitment_hc_slot_round",
        "recruitment_hc_slots",
        ["tenant_id", "position_id", "slot_number", "recruitment_round"],
    )

    op.execute('ALTER TABLE "offers" DISABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "recruitment_hc_slots" DISABLE ROW LEVEL SECURITY')
    bind = op.get_bind()
    released_offers = bind.execute(sa.text("""
        SELECT id, tenant_id, resume_id, position_id, accepted_at,
               actual_onboarded_at, departed_at
        FROM offers
        WHERE departure_released_hc IS TRUE
          AND departed_at IS NOT NULL
    """)).mappings().all()
    for offer in released_offers:
        current = bind.execute(sa.text("""
            SELECT id, slot_number, recruitment_round, assigned_at,
                   round_started_at, created_at
            FROM recruitment_hc_slots
            WHERE tenant_id = :tenant_id
              AND position_id = :position_id
              AND candidate_resume_id IS NULL
              AND recruitment_round > 1
              AND round_started_at = :departed_at
            ORDER BY recruitment_round DESC
            LIMIT 1
        """), offer).mappings().first()
        if current is None:
            continue
        historical_round = current["recruitment_round"] - 1
        exists = bind.execute(sa.text("""
            SELECT 1
            FROM recruitment_hc_slots
            WHERE tenant_id = :tenant_id
              AND position_id = :position_id
              AND slot_number = :slot_number
              AND recruitment_round = :historical_round
        """), {
            **offer,
            "slot_number": current["slot_number"],
            "historical_round": historical_round,
        }).first()
        if exists is None:
            bind.execute(sa.text("""
                INSERT INTO recruitment_hc_slots (
                    id, tenant_id, position_id, slot_number, status,
                    assigned_at, round_started_at, accepted_at, completed_at,
                    candidate_resume_id, recruitment_round, status_reason, created_at
                ) VALUES (
                    :id, :tenant_id, :position_id, :slot_number, 'released',
                    :assigned_at, :round_started_at, :accepted_at, :completed_at,
                    :resume_id, :historical_round,
                    '员工离职，HC已释放，历史积分已冻结', :created_at
                )
            """), {
                **offer,
                "id": uuid.uuid4(),
                "slot_number": current["slot_number"],
                "historical_round": historical_round,
                "assigned_at": current["assigned_at"],
                "round_started_at": current["assigned_at"],
                "completed_at": offer["actual_onboarded_at"],
                "created_at": current["created_at"],
            })
        bind.execute(sa.text("""
            UPDATE recruitment_hc_slots
            SET assigned_at = :departed_at,
                status_reason = 'HC释放后开启新一轮招聘'
            WHERE id = :slot_id
        """), {"departed_at": offer["departed_at"], "slot_id": current["id"]})

    bind.execute(sa.text("""
        UPDATE recruitment_hc_slots AS slot
        SET status = 'departed_retained',
            status_reason = '员工离职，HC未释放，历史积分已冻结'
        FROM offers AS offer
        WHERE offer.departure_released_hc IS FALSE
          AND offer.departed_at IS NOT NULL
          AND slot.tenant_id = offer.tenant_id
          AND slot.position_id = offer.position_id
          AND slot.candidate_resume_id = offer.resume_id
    """))
    op.execute('ALTER TABLE "offers" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "offers" FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "recruitment_hc_slots" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "recruitment_hc_slots" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_constraint(
        "uq_recruitment_hc_slot_round",
        "recruitment_hc_slots",
        type_="unique",
    )
    op.execute("""
        DELETE FROM recruitment_hc_slots AS newer
        USING recruitment_hc_slots AS older
        WHERE newer.tenant_id = older.tenant_id
          AND newer.position_id = older.position_id
          AND newer.slot_number = older.slot_number
          AND newer.recruitment_round > older.recruitment_round
    """)
    op.execute("""
        UPDATE recruitment_hc_slots
        SET status = CASE
                WHEN status IN ('released', 'departed_retained') THEN 'completed'
                ELSE status
            END,
            status_reason = NULL
    """)
    op.create_unique_constraint(
        "uq_recruitment_hc_slot_number",
        "recruitment_hc_slots",
        ["tenant_id", "position_id", "slot_number"],
    )
