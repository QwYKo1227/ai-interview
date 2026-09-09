"""add departed resume status and backfill registered departures

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
"""

from alembic import op


revision = "k2l3m4n5o6p7"
down_revision = "j1k2l3m4n5o6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL requires the enum value to be committed before it can be used
    # by the data backfill below.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE resumestatus ADD VALUE IF NOT EXISTS 'DEPARTED'")

    op.execute('ALTER TABLE "offers" DISABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "resumes" DISABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "resume_status_events" DISABLE ROW LEVEL SECURITY')

    op.execute("""
        UPDATE resumes AS resume
        SET status = 'DEPARTED'::resumestatus
        FROM offers AS offer
        WHERE offer.tenant_id = resume.tenant_id
          AND offer.resume_id = resume.id
          AND (offer.status::text = 'DEPARTED' OR offer.departed_at IS NOT NULL)
    """)
    op.execute("""
        UPDATE resume_status_events AS event
        SET new_status = 'departed'
        FROM offers AS offer
        WHERE event.tenant_id = offer.tenant_id
          AND event.source = 'departure_registration'
          AND event.source_id = offer.id
          AND (offer.status::text = 'DEPARTED' OR offer.departed_at IS NOT NULL)
    """)
    op.execute("""
        INSERT INTO resume_status_events (
            id, tenant_id, resume_id, old_status, new_status,
            source, source_id, actor_id, reason, occurred_at
        )
        SELECT
            gen_random_uuid(), offer.tenant_id, offer.resume_id,
            'completed', 'departed', 'departure_registration', offer.id,
            offer.departure_recorded_by, offer.departure_reason, offer.departed_at
        FROM offers AS offer
        WHERE (offer.status::text = 'DEPARTED' OR offer.departed_at IS NOT NULL)
          AND offer.departed_at IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM resume_status_events AS event
              WHERE event.tenant_id = offer.tenant_id
                AND event.source = 'departure_registration'
                AND event.source_id = offer.id
          )
    """)

    op.execute('ALTER TABLE "offers" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "offers" FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "resumes" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "resumes" FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "resume_status_events" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "resume_status_events" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    # PostgreSQL cannot safely remove an enum label while historical rows may
    # still reference it. Retain the additive status on downgrade.
    pass
