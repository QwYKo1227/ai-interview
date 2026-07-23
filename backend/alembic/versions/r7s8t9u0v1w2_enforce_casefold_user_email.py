"""enforce case-insensitive tenant user email uniqueness

Revision ID: r7s8t9u0v1w2
Revises: q6r7s8t9u0v1
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "r7s8t9u0v1w2"
down_revision: Union[str, None] = "q6r7s8t9u0v1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    # The preceding isolation migration FORCEs RLS. The migration owner must
    # deliberately and transactionally expose all rows for a global conflict
    # gate; a failed migration rolls this DDL back and leaves FORCE enabled.
    op.execute("ALTER TABLE users NO FORCE ROW LEVEL SECURITY")
    conflicts = connection.execute(
        sa.text(
            "SELECT tenant_id, lower(btrim(email)), count(*) FROM users "
            "WHERE email IS NOT NULL GROUP BY tenant_id, lower(btrim(email)) "
            "HAVING count(*) > 1"
        )
    ).fetchall()
    if conflicts:
        raise RuntimeError(
            "case-insensitive user email conflicts must be resolved before migration "
            f"(groups={len(conflicts)})"
        )

    op.execute("UPDATE users SET email = lower(btrim(email))")
    op.drop_constraint("uq_users_tenant_email", "users", type_="unique")
    op.create_index(
        "uq_users_tenant_lower_email",
        "users",
        ["tenant_id", sa.text("lower(email)")],
        unique=True,
    )
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE users NO FORCE ROW LEVEL SECURITY")
    op.drop_index("uq_users_tenant_lower_email", table_name="users")
    op.create_unique_constraint(
        "uq_users_tenant_email", "users", ["tenant_id", "email"]
    )
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
