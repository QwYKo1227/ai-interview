"""track manual resume screening decisions

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
"""

from alembic import op
import sqlalchemy as sa


revision = "l3m4n5o6p7q8"
down_revision = "k2l3m4n5o6p7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resumes",
        sa.Column(
            "manual_screening_decision",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Older overrides have no dedicated audit record. Preserve cases where the
    # current early-stage status cannot have come from the stored AI score.
    op.execute('ALTER TABLE "resumes" DISABLE ROW LEVEL SECURITY')
    op.execute(
        """
        UPDATE resumes
        SET manual_screening_decision = true
        WHERE hr_review IS NOT NULL
           OR rejected_by IS NOT NULL
           OR (status::text = 'PENDING_REVIEW' AND match_score < 60)
           OR (status::text = 'WAITLIST' AND (
                match_score >= 60 OR screening_result::text <> 'WAITLIST'
           ))
        """
    )
    op.execute('ALTER TABLE "resumes" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "resumes" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_column("resumes", "manual_screening_decision")
