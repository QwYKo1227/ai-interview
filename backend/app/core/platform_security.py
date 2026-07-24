from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.core.security import ALGORITHM, SECRET_KEY
from app.config.database import get_unscoped_db
from app.core.host_policy import resolve_request_origin
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class PlatformAccessTokenClaims:
    user_id: UUID


platform_oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="api/platform/auth/login",
    scheme_name="PlatformBearer",
)


def create_platform_access_token(
    *, user_id: UUID, expires_delta: timedelta | None = None
) -> str:
    if not isinstance(user_id, UUID):
        raise TypeError("user_id must be a UUID")
    expiration = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=60)
    )
    return jwt.encode(
        {
            "sub": str(user_id),
            "token_type": "platform",
            "exp": expiration,
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_platform_access_token(token: str) -> PlatformAccessTokenClaims:
    payload = jwt.decode(
        token,
        SECRET_KEY,
        algorithms=[ALGORITHM],
        options={"require_sub": True, "require_exp": True},
    )
    if payload.get("token_type") != "platform":
        raise JWTError("token_type must be platform")
    if "tenant_id" in payload or "role" in payload:
        raise JWTError("tenant claims are forbidden in platform tokens")
    subject = payload.get("sub")
    expiration = payload.get("exp")
    if not isinstance(subject, str):
        raise JWTError("sub must be a UUID string")
    if isinstance(expiration, bool) or not isinstance(expiration, (int, float)):
        raise JWTError("exp must be a numeric date")
    try:
        user_id = UUID(subject)
    except (TypeError, ValueError) as exc:
        raise JWTError("invalid platform identity claims") from exc
    return PlatformAccessTokenClaims(user_id=user_id)


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate platform credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_platform_access_token_claims(
    request: Request,
    token: str = Depends(platform_oauth2_scheme),
    db: Session = Depends(get_unscoped_db),
) -> PlatformAccessTokenClaims:
    resolve_request_origin(db, request)
    try:
        return decode_platform_access_token(token)
    except JWTError as exc:
        raise _credentials_exception() from exc
