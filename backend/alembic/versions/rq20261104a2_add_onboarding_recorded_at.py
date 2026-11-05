"""Record the actual onboarding registration operation, without inventing history."""
from alembic import op
import sqlalchemy as sa

revision = "rq20261104a2"
down_revision = "rq20261103a1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("offers", sa.Column("onboarding_recorded_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("offers", "onboarding_recorded_at")
