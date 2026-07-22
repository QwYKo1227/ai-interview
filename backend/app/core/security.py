import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.models.models import User, UserRole


load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY") or os.getenv("JWT_SECRET")
if not SECRET_KEY:
    if os.getenv("APP_ENV", "development") == "production":
        raise RuntimeError("SECRET_KEY is required in production.")
    SECRET_KEY = "dev-secret-key-change-me"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 * 24 * 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    tenant_id: UUID
    role: str


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(
    *,
    user_id: UUID,
    tenant_id: UUID,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    if not isinstance(user_id, UUID):
        raise TypeError("user_id must be a UUID")
    if not isinstance(tenant_id, UUID):
        raise TypeError("tenant_id must be a UUID")
    if not isinstance(role, str) or not role:
        raise TypeError("role must be a non-empty string")

    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=15)
    )
    claims = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "token_type": "tenant",
        "exp": expire,
    }
    return jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> AccessTokenClaims:
    payload = jwt.decode(
        token,
        SECRET_KEY,
        algorithms=[ALGORITHM],
        options={"require_sub": True, "require_exp": True},
    )

    subject = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    role = payload.get("role")
    token_type = payload.get("token_type")
    expiration = payload.get("exp")
    if not isinstance(subject, str):
        raise JWTError("sub must be a UUID string")
    if not isinstance(tenant_id, str):
        raise JWTError("tenant_id must be a UUID string")
    if not isinstance(role, str) or not role:
        raise JWTError("role must be a non-empty string")
    if token_type != "tenant":
        raise JWTError("token_type must be tenant")
    if isinstance(expiration, bool) or not isinstance(expiration, (int, float)):
        raise JWTError("exp must be a numeric date")

    try:
        user_id_value = UUID(subject)
        tenant_id_value = UUID(tenant_id)
        role_value = UserRole(role).value
    except (TypeError, ValueError) as exc:
        raise JWTError("invalid tenant identity claims") from exc

    return AccessTokenClaims(
        user_id=user_id_value,
        tenant_id=tenant_id_value,
        role=role_value,
    )


def check_roles(required_roles: list[UserRole]):
    # Import when the dependency factory is used so token primitives remain
    # independent from the request dependency module.
    from app.core.tenant_dependencies import get_current_user_dep

    def role_checker(current_user: User = Depends(get_current_user_dep)):
        if current_user.role not in required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted",
            )
        return current_user

    return role_checker
