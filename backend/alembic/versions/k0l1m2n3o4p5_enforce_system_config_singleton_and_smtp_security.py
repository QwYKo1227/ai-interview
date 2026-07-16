"""强制系统配置单例并新增 SMTP 安全连接方式

Revision ID: k0l1m2n3o4p5
Revises: j9k0l1m2n3o4
Create Date: 2026-07-16

"""
from alembic import op
import sqlalchemy as sa


revision = "k0l1m2n3o4p5"
down_revision = "j9k0l1m2n3o4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "system_configs",
        sa.Column("smtp_security", sa.String(), nullable=False, server_default=sa.text("'ssl'")),
    )
    op.add_column(
        "system_configs",
        sa.Column("singleton_key", sa.Boolean(), nullable=True),
    )

    # 保留最近更新的记录；删除历史重复记录前，仅用旧记录补齐主记录的空字段。
    bind = op.get_bind()
    metadata = sa.MetaData()
    configs = sa.Table("system_configs", metadata, autoload_with=bind)
    rows = bind.execute(
        sa.select(configs).order_by(
            configs.c.updated_at.desc().nullslast(), configs.c.id.desc()
        )
    ).mappings().all()
    if rows:
        canonical = rows[0]
        fields_to_merge = (
            "llm_provider", "llm_base_url", "llm_api_key", "llm_model",
            "llm_temperature", "llm_max_tokens", "smtp_host", "smtp_port",
            "smtp_username", "smtp_password", "mail_from", "mail_from_name",
            "mail_enabled", "frontend_url", "prompt_configs",
        )
        updates = {"singleton_key": True}
        for field in fields_to_merge:
            if canonical[field] is None:
                updates[field] = next(
                    (row[field] for row in rows[1:] if row[field] is not None), None
                )
        bind.execute(
            configs.update().where(configs.c.id == canonical["id"]).values(**updates)
        )
        if len(rows) > 1:
            bind.execute(
                configs.delete().where(configs.c.id.in_([row["id"] for row in rows[1:]]))
            )
    op.alter_column("system_configs", "singleton_key", nullable=False)
    op.create_unique_constraint(
        "uq_system_configs_singleton_key", "system_configs", ["singleton_key"]
    )
    op.create_check_constraint(
        "ck_system_configs_singleton_key_true",
        "system_configs",
        "singleton_key IS TRUE",
    )


def downgrade():
    op.drop_constraint("ck_system_configs_singleton_key_true", "system_configs", type_="check")
    op.drop_constraint("uq_system_configs_singleton_key", "system_configs", type_="unique")
    op.drop_column("system_configs", "singleton_key")
    op.drop_column("system_configs", "smtp_security")
