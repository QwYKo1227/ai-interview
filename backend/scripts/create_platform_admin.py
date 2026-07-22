"""Idempotently create the platform administrator from environment variables."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config.tenant_session import TenantCapableSession
from app.core.security import get_password_hash
from app.models.tenant_models import PlatformUser


class PlatformAdminInputError(ValueError):
    """A safe validation error that never contains credentials."""


@dataclass(frozen=True)
class PlatformAdminResult:
    user: PlatformUser
    created: bool


def _normalized_email(value: str) -> str:
    if not isinstance(value, str):
        raise PlatformAdminInputError("platform admin email is required")
    candidate = value.strip().lower()
    try:
        normalized = str(TypeAdapter(EmailStr).validate_python(candidate)).lower()
    except ValidationError:
        raise PlatformAdminInputError("platform admin email is invalid") from None
    if len(normalized) > 255:
        raise PlatformAdminInputError("platform admin email is invalid")
    return normalized


def _validated_password(value: str) -> str:
    if not isinstance(value, str):
        raise PlatformAdminInputError("platform admin password is required")
    if len(value) < 12 or len(value.encode("utf-8")) > 72:
        raise PlatformAdminInputError("platform admin password does not meet policy")
    if not any(character.isalpha() for character in value):
        raise PlatformAdminInputError("platform admin password does not meet policy")
    if not any(character.isdigit() for character in value):
        raise PlatformAdminInputError("platform admin password does not meet policy")
    return value


def create_platform_admin(db: Session, email: str, password: str) -> PlatformAdminResult:
    """Create once; a repeated invocation never changes the stored password."""

    normalized_email = _normalized_email(email)
    validated_password = _validated_password(password)
    try:
        existing = (
            db.query(PlatformUser)
            .filter(PlatformUser.email == normalized_email)
            .first()
        )
        if existing is not None:
            db.commit()
            return PlatformAdminResult(user=existing, created=False)

        user = PlatformUser(
            email=normalized_email,
            hashed_password=get_password_hash(validated_password),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return PlatformAdminResult(user=user, created=True)
    except Exception:
        db.rollback()
        raise


def _require_migration_role(db: Session) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    if db.execute(text("SELECT current_user")).scalar_one() != "app_migration":
        raise RuntimeError("migration database role is required")


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
        normalized_email = _normalized_email(email)
        _validated_password(password)
        engine = create_engine(url)
        factory = sessionmaker(bind=engine, class_=TenantCapableSession)
        with factory() as db:
            _require_migration_role(db)
            result = create_platform_admin(db, normalized_email, password)
        print(
            json.dumps(
                {
                    "ok": True,
                    "email": normalized_email,
                    "result": "created" if result.created else "already_exists",
                },
                sort_keys=True,
            ),
            file=stdout,
        )
        return 0
    except Exception:
        print(
            json.dumps(
                {"ok": False, "error": "platform administrator initialization failed"},
                sort_keys=True,
            ),
            file=stdout,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
