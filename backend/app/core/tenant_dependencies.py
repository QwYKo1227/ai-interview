from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.config.database import get_unscoped_db
from app.config.tenant_session import TenantSession, tenant_session
from app.core.security import AccessTokenClaims, decode_access_token
from app.core.tenant_context import TenantContext
from app.models.models import User
from app.models.tenant_models import Tenant, TenantDomain, TenantStatus


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/token")


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_access_token_claims(token: str = Depends(oauth2_scheme)) -> AccessTokenClaims:
    try:
        return decode_access_token(token)
    except JWTError as exc:
        raise _credentials_exception() from exc


def _normalized_request_host(request: Request) -> str:
    host = request.headers.get("host", "").strip().lower()
    if host.startswith("["):
        closing_bracket = host.find("]")
        return host[1:closing_bracket] if closing_bracket > 0 else ""
    return host.partition(":")[0]


def get_tenant_context(
    request: Request,
    claims: AccessTokenClaims = Depends(get_access_token_claims),
    db: Session = Depends(get_unscoped_db),
) -> TenantContext:
    hostname = _normalized_request_host(request)
    domain = None
    if hostname:
        domain = (
            db.query(TenantDomain)
            .filter(TenantDomain.domain == hostname)
            .first()
        )
    if domain is not None and domain.tenant_id != claims.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token tenant does not match request domain",
        )

    tenant = (
        db.query(Tenant)
        .filter(
            Tenant.id == claims.tenant_id,
            Tenant.status == TenantStatus.ACTIVE,
        )
        .first()
    )
    if tenant is None:
        raise _credentials_exception()

    return TenantContext(
        tenant_id=tenant.id,
        tenant_code=tenant.code,
        source="jwt",
    )


def get_tenant_db(
    context: TenantContext = Depends(get_tenant_context),
) -> Iterator[TenantSession]:
    with tenant_session(context.tenant_id) as db:
        yield db


def get_current_user_dep(
    claims: AccessTokenClaims = Depends(get_access_token_claims),
    db: TenantSession = Depends(get_tenant_db),
) -> User:
    user = (
        db.query(User)
        .filter(
            User.id == claims.user_id,
            User.tenant_id == claims.tenant_id,
        )
        .first()
    )
    if user is None:
        raise _credentials_exception()
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用，请联系管理员",
        )
    return user
