from typing import Any, Mapping, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.models import SystemConfig


def get_system_config(db: Session) -> Optional[SystemConfig]:
    """读取唯一的系统配置记录；不存在时返回空。"""
    return (
        db.query(SystemConfig)
        .filter(SystemConfig.singleton_key.is_(True))
        .one_or_none()
    )


def get_or_create_system_config(
    db: Session, defaults: Optional[Mapping[str, Any]] = None
) -> SystemConfig:
    """读取系统配置；不存在时创建并持久化唯一记录。"""
    config = get_system_config(db)
    if config:
        return config

    config = SystemConfig(singleton_key=True, **dict(defaults or {}))
    db.add(config)
    try:
        db.commit()
        db.refresh(config)
    except IntegrityError:
        # 另一请求可能已并发创建该单例，回滚后重新读取即可。
        db.rollback()
        config = get_system_config(db)
        if config:
            return config
        raise
    return config
