"""add mail config fields to system_configs

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-03-06

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    # Fresh Alembic installs create system_configs in h8i9j0k1l2m3, which
    # already contains these fields. This earlier revision only upgrades
    # legacy databases whose table was created by SQLAlchemy metadata.
    if not sa.inspect(op.get_bind()).has_table('system_configs'):
        return
    # 添加邮件服务配置字段
    op.add_column('system_configs', sa.Column('smtp_host', sa.String(), nullable=True))
    op.add_column('system_configs', sa.Column('smtp_port', sa.Integer(), nullable=True, server_default='465'))
    op.add_column('system_configs', sa.Column('smtp_username', sa.String(), nullable=True))
    op.add_column('system_configs', sa.Column('smtp_password', sa.String(), nullable=True))
    op.add_column('system_configs', sa.Column('mail_from', sa.String(), nullable=True))
    op.add_column('system_configs', sa.Column('mail_from_name', sa.String(), nullable=True, server_default='招聘系统'))
    op.add_column('system_configs', sa.Column('mail_enabled', sa.Boolean(), nullable=True, server_default='false'))


def downgrade():
    if not sa.inspect(op.get_bind()).has_table('system_configs'):
        return
    op.drop_column('system_configs', 'mail_enabled')
    op.drop_column('system_configs', 'mail_from_name')
    op.drop_column('system_configs', 'mail_from')
    op.drop_column('system_configs', 'smtp_password')
    op.drop_column('system_configs', 'smtp_username')
    op.drop_column('system_configs', 'smtp_port')
    op.drop_column('system_configs', 'smtp_host')
