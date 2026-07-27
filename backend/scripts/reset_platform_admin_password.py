"""Reset an existing platform administrator password from environment variables."""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config.tenant_session import TenantCapableSession
from app.core.security import get_password_hash
from app.models.tenant_models import PlatformUser
from scripts.create_platform_admin import (
    PlatformAdminInputError,
    _normalized_email,
    _require_migration_role,
    _validated_password,
)


class PlatformAdminNotFoundError(LookupError):
    """Raised when the requested platform administrator does not exist."""


def _resolve_platform_admin_email(db: Session, email: str | None) -> str:
    if email:
        return _normalized_email(email)

    users = db.query(PlatformUser).order_by(PlatformUser.email).limit(2).all()
    if len(users) != 1:
        raise PlatformAdminInputError(
            "PLATFORM_ADMIN_EMAIL is required unless exactly one account exists"
        )
    return users[0].email


def _prompt_for_password(password_reader=getpass.getpass) -> str:
    first = password_reader("请输入平台管理员新密码: ")
    second = password_reader("请再次输入新密码: ")
    if first != second:
        raise PlatformAdminInputError("两次输入的密码不一致，请重新执行")
    return first


def _interactive_environ(environ=None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    result = dict(source)
    if not result.get("PLATFORM_ADMIN_PASSWORD") and sys.stdin.isatty():
        result["PLATFORM_ADMIN_PASSWORD"] = _prompt_for_password()
    return result


def reset_platform_admin_password(
    db: Session,
    email: str,
    password: str,
) -> PlatformUser:
    """Replace the password hash for an existing platform administrator."""

    normalized_email = _normalized_email(email)
    validated_password = _validated_password(password)
    try:
        user = (
            db.query(PlatformUser)
            .filter(PlatformUser.email == normalized_email)
            .first()
        )
        if user is None:
            raise PlatformAdminNotFoundError(
                "platform administrator does not exist"
            )

        user.hashed_password = get_password_hash(validated_password)
        db.commit()
        db.refresh(user)
        return user
    except Exception:
        db.rollback()
        raise


def run_cli(*, environ=None, stdout=None) -> int:
    environ = os.environ if environ is None else environ
    stdout = sys.stdout if stdout is None else stdout
    url = environ.get("MIGRATION_DATABASE_URL")
    email = environ.get("PLATFORM_ADMIN_EMAIL")
    password = environ.get("PLATFORM_ADMIN_PASSWORD")
    engine = None
    try:
        if not url:
            raise PlatformAdminInputError("MIGRATION_DATABASE_URL is required")
        _validated_password(password)
        engine = create_engine(url)
        factory = sessionmaker(bind=engine, class_=TenantCapableSession)
        with factory() as db:
            _require_migration_role(db)
            resolved_email = _resolve_platform_admin_email(db, email)
            reset_platform_admin_password(
                db,
                resolved_email,
                password,
            )
        print(
            json.dumps(
                {
                    "ok": True,
                    "email": resolved_email,
                    "result": "password_reset",
                },
                sort_keys=True,
            ),
            file=stdout,
        )
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "platform administrator password reset failed",
                },
                sort_keys=True,
            ),
            file=stdout,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


def main() -> int:
    try:
        environ = _interactive_environ()
    except PlatformAdminInputError as error:
        print(f"密码重置失败：{error}", file=sys.stderr)
        return 1

    status = run_cli(environ=environ)
    if status == 0:
        print("平台管理员密码已修改。")
    elif sys.stdin.isatty():
        print("密码重置失败，请检查密码规则或管理员账号数量。", file=sys.stderr)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
