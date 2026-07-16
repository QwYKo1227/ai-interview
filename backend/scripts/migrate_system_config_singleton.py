"""安全升级既有 system_configs 表到单例结构。

该项目的早期部署通过 SQLAlchemy 的 create_all 建表，未写入 Alembic 版本表。
因此本脚本不回放历史迁移，只处理本次系统配置单例与 SMTP 安全方式所需的变更。
"""
import logging
import os
from typing import Any, Mapping, Sequence

from sqlalchemy import MetaData, Table, create_engine, inspect, text


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MERGE_FIELDS = (
    "llm_provider", "llm_base_url", "llm_api_key", "llm_model",
    "llm_temperature", "llm_max_tokens", "smtp_host", "smtp_port",
    "smtp_username", "smtp_password", "mail_from", "mail_from_name",
    "mail_enabled", "frontend_url", "prompt_configs",
)
PREVIOUS_ALEMBIC_VERSION = "j9k0l1m2n3o4"
TARGET_ALEMBIC_VERSION = "k0l1m2n3o4p5"


def _is_missing(value: Any) -> bool:
    """空字符串和空 JSON 可由旧记录补齐；False 是有效的开关值。"""
    return value is None or (isinstance(value, str) and not value.strip()) or value in ({}, [])


def target_alembic_version(current_version: str | None) -> str | None:
    """仅为本脚本能安全替代的已知 Alembic 版本推进标记。"""
    if current_version is None:
        return None
    if current_version in {PREVIOUS_ALEMBIC_VERSION, TARGET_ALEMBIC_VERSION}:
        return TARGET_ALEMBIC_VERSION
    raise RuntimeError(f"未知的 Alembic 版本：{current_version}；请先人工确认升级路径")


def get_alembic_version_transition(connection) -> tuple[str | None, str | None]:
    """在执行任何 DDL 前验证 Alembic 版本，避免未知库被部分修改。"""
    if not inspect(connection).has_table("alembic_version"):
        return None, None
    current_version = connection.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar_one_or_none()
    return current_version, target_alembic_version(current_version)


def synchronize_alembic_version(
    connection, current_version: str | None, target_version: str | None
) -> None:
    """在结构更新成功后同步 Alembic 版本，避免重复执行本次迁移。"""
    if target_version and current_version != target_version:
        connection.execute(
            text("UPDATE alembic_version SET version_num = :version_num"),
            {"version_num": target_version},
        )
        logger.info("Alembic 版本已同步为 %s", target_version)


def merge_system_configs(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[Any]]:
    """保留已按更新时间倒序排列的首条记录，并补齐其中的空字段。"""
    canonical = dict(rows[0])
    duplicates = list(rows[1:])
    for field in MERGE_FIELDS:
        if _is_missing(canonical.get(field)):
            replacement = next(
                (
                    row.get(field)
                    for row in duplicates
                    if not _is_missing(row.get(field))
                ),
                None,
            )
            if replacement is not None:
                canonical[field] = replacement
    return canonical, [row["id"] for row in duplicates]


def upgrade_system_config_table(connection) -> None:
    """以幂等方式更新已有 PostgreSQL 表，不依赖 Alembic 历史。"""
    if not inspect(connection).has_table("system_configs"):
        logger.info("未发现 system_configs 表；应用首次启动会按当前模型创建该表。")
        return

    current_version, target_version = get_alembic_version_transition(connection)

    columns = {column["name"] for column in inspect(connection).get_columns("system_configs")}
    if "smtp_security" not in columns:
        connection.execute(text("ALTER TABLE system_configs ADD COLUMN smtp_security VARCHAR DEFAULT 'ssl'"))
    if "singleton_key" not in columns:
        connection.execute(text("ALTER TABLE system_configs ADD COLUMN singleton_key BOOLEAN DEFAULT TRUE"))

    connection.execute(
        text(
            "UPDATE system_configs SET smtp_security = 'ssl' "
            "WHERE smtp_security IS NULL OR BTRIM(smtp_security) = ''"
        )
    )
    synchronize_alembic_version(connection, current_version, target_version)
    configs = Table("system_configs", MetaData(), autoload_with=connection)
    rows = connection.execute(
        configs.select().order_by(configs.c.updated_at.desc().nullslast(), configs.c.id.desc())
    ).mappings().all()

    if rows:
        canonical, duplicate_ids = merge_system_configs(rows)
        canonical["singleton_key"] = True
        canonical["smtp_security"] = (
            canonical.get("smtp_security")
            if canonical.get("smtp_security") in {"ssl", "starttls"}
            else "ssl"
        )
        values = {
            field: canonical[field]
            for field in (*MERGE_FIELDS, "smtp_security", "singleton_key")
            if field in canonical
        }
        connection.execute(
            configs.update().where(configs.c.id == canonical["id"]).values(**values)
        )
        for duplicate_id in duplicate_ids:
            connection.execute(
                configs.delete().where(configs.c.id == duplicate_id)
            )
        logger.info(
            "系统配置已合并：保留 id=%s，删除重复记录 id=%s",
            canonical["id"],
            duplicate_ids,
        )

    connection.execute(text("ALTER TABLE system_configs ALTER COLUMN smtp_security SET DEFAULT 'ssl'"))
    connection.execute(text("ALTER TABLE system_configs ALTER COLUMN smtp_security SET NOT NULL"))
    connection.execute(text("ALTER TABLE system_configs ALTER COLUMN singleton_key SET DEFAULT TRUE"))
    connection.execute(text("ALTER TABLE system_configs ALTER COLUMN singleton_key SET NOT NULL"))
    connection.execute(
        text(
            """
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_system_configs_singleton_key'
                ) THEN
                    ALTER TABLE system_configs ADD CONSTRAINT uq_system_configs_singleton_key UNIQUE (singleton_key);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'ck_system_configs_singleton_key_true'
                ) THEN
                    ALTER TABLE system_configs ADD CONSTRAINT ck_system_configs_singleton_key_true CHECK (singleton_key IS TRUE);
                END IF;
            END $$;
            """
        )
    )


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        upgrade_system_config_table(connection)


if __name__ == "__main__":
    main()
