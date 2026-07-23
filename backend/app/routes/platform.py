from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.config.database import get_unscoped_db
from app.core.platform_security import (
    PlatformAccessTokenClaims,
    create_platform_access_token,
    get_platform_access_token_claims,
)
from app.core.security import verify_password
from app.core.rate_limit import enforce_rate_limit
from app.models.tenant_models import PlatformUser
from app.models.tenant_models import Tenant, TenantDomain
from app.schemas.tenant import (
    PlatformLoginRequest,
    TenantDetailResponse,
    TenantDomainCreate,
    TenantDomainResponse,
    TenantDomainUpdate,
    TenantOnboardingRequest,
    TenantResponse,
    TenantStatusUpdate,
)
from app.schemas.user import Token
from app.services.tenant_service import (
    PRIMARY_DOMAIN_MESSAGE,
    TENANT_ACTOR_MESSAGE,
    TENANT_CONFLICT_MESSAGE,
    TENANT_NOT_FOUND_MESSAGE,
    TENANT_ONBOARDING_MESSAGE,
    TenantActorError,
    TenantConflictError,
    TenantNotFoundError,
    TenantOnboardingError,
    add_tenant_domain,
    create_tenant_with_admin,
    delete_tenant_domain,
    set_tenant_status,
    update_tenant_domain,
)
from typing import List
from uuid import UUID


class SafePlatformRoute(APIRoute):
    """Keep rejected platform-control inputs out of error responses."""

    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def safe_handler(request: Request):
            try:
                return await original_handler(request)
            except RequestValidationError:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Invalid platform request",
                ) from None

        return safe_handler


router = APIRouter(
    prefix="/platform",
    tags=["platform"],
    route_class=SafePlatformRoute,
)

PLATFORM_LOGIN_ERROR = "Invalid email or password"
DUMMY_PASSWORD_HASH = "$2b$12$b2EfUH39fOFct42kb2HHv.Uq3Dml9R3urPsHrAu.F5E87KLizmY5C"


@router.post("/auth/login", response_model=Token)
def platform_login(
    payload: PlatformLoginRequest,
    request: Request = None,
    db: Session = Depends(get_unscoped_db),
):
    # Keep the callable usable by trusted maintenance/integration code that
    # invokes the route function directly; HTTP requests always receive a
    # Starlette Request from FastAPI and are rate limited.
    if request is not None:
        enforce_rate_limit(request, "login", "platform", str(payload.email))
    user = (
        db.query(PlatformUser)
        .filter(PlatformUser.email == str(payload.email))
        .first()
    )
    password_hash = (
        user.hashed_password
        if user is not None and user.is_active
        else DUMMY_PASSWORD_HASH
    )
    password_matches = verify_password(payload.password, password_hash)
    if user is None or not user.is_active or not password_matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=PLATFORM_LOGIN_ERROR,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(
        access_token=create_platform_access_token(user_id=user.id),
        token_type="bearer",
    )


@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def create_tenant(
    payload: TenantOnboardingRequest,
    claims: PlatformAccessTokenClaims = Depends(get_platform_access_token_claims),
    db: Session = Depends(get_unscoped_db),
):
    try:
        return create_tenant_with_admin(db, payload, actor_id=claims.user_id)
    except TenantConflictError:
        raise HTTPException(status_code=409, detail=TENANT_CONFLICT_MESSAGE) from None
    except TenantActorError:
        raise HTTPException(status_code=403, detail=TENANT_ACTOR_MESSAGE) from None
    except TenantOnboardingError:
        raise HTTPException(status_code=500, detail=TENANT_ONBOARDING_MESSAGE) from None


def _parse_tenant_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=404, detail=TENANT_NOT_FOUND_MESSAGE) from None


def _attach_primary_domain(db: Session, tenant: Tenant) -> Tenant:
    tenant.primary_domain = (
        db.query(TenantDomain.domain)
        .filter(
            TenantDomain.tenant_id == tenant.id,
            TenantDomain.is_primary.is_(True),
        )
        .scalar()
    )
    return tenant


@router.get("/tenants", response_model=List[TenantResponse])
def list_tenants(
    _claims: PlatformAccessTokenClaims = Depends(get_platform_access_token_claims),
    db: Session = Depends(get_unscoped_db),
):
    return [
        _attach_primary_domain(db, tenant)
        for tenant in db.query(Tenant).order_by(Tenant.code).all()
    ]


@router.get("/tenants/{tenant_id}", response_model=TenantDetailResponse)
def get_tenant_detail(
    tenant_id: str,
    _claims: PlatformAccessTokenClaims = Depends(get_platform_access_token_claims),
    db: Session = Depends(get_unscoped_db),
):
    tenant = db.query(Tenant).filter(Tenant.id == _parse_tenant_id(tenant_id)).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail=TENANT_NOT_FOUND_MESSAGE)
    _attach_primary_domain(db, tenant)
    return TenantDetailResponse.model_validate(
        {
            **TenantResponse.model_validate(tenant).model_dump(),
            "domains": db.query(TenantDomain)
            .filter(TenantDomain.tenant_id == tenant.id)
            .order_by(TenantDomain.created_at, TenantDomain.domain)
            .all(),
        }
    )


@router.post(
    "/tenants/{tenant_id}/domains",
    response_model=TenantDomainResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_tenant_domain(
    tenant_id: str,
    payload: TenantDomainCreate,
    claims: PlatformAccessTokenClaims = Depends(get_platform_access_token_claims),
    db: Session = Depends(get_unscoped_db),
):
    try:
        return add_tenant_domain(
            db,
            tenant_id=_parse_tenant_id(tenant_id),
            payload=payload,
            actor_id=claims.user_id,
        )
    except TenantNotFoundError:
        raise HTTPException(status_code=404, detail=TENANT_NOT_FOUND_MESSAGE) from None
    except TenantConflictError:
        raise HTTPException(status_code=409, detail=TENANT_CONFLICT_MESSAGE) from None
    except TenantActorError:
        raise HTTPException(status_code=403, detail=TENANT_ACTOR_MESSAGE) from None
    except TenantOnboardingError:
        raise HTTPException(status_code=500, detail=TENANT_ONBOARDING_MESSAGE) from None


@router.patch(
    "/tenants/{tenant_id}/domains/{domain_id}",
    response_model=TenantDomainResponse,
)
def patch_tenant_domain(
    tenant_id: str,
    domain_id: str,
    payload: TenantDomainUpdate,
    claims: PlatformAccessTokenClaims = Depends(get_platform_access_token_claims),
    db: Session = Depends(get_unscoped_db),
):
    try:
        return update_tenant_domain(
            db,
            tenant_id=_parse_tenant_id(tenant_id),
            domain_id=_parse_tenant_id(domain_id),
            payload=payload,
            actor_id=claims.user_id,
        )
    except TenantNotFoundError:
        raise HTTPException(status_code=404, detail=TENANT_NOT_FOUND_MESSAGE) from None
    except TenantConflictError:
        raise HTTPException(status_code=409, detail=PRIMARY_DOMAIN_MESSAGE) from None
    except TenantActorError:
        raise HTTPException(status_code=403, detail=TENANT_ACTOR_MESSAGE) from None
    except TenantOnboardingError:
        raise HTTPException(status_code=500, detail=TENANT_ONBOARDING_MESSAGE) from None


@router.delete(
    "/tenants/{tenant_id}/domains/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_tenant_domain(
    tenant_id: str,
    domain_id: str,
    claims: PlatformAccessTokenClaims = Depends(get_platform_access_token_claims),
    db: Session = Depends(get_unscoped_db),
):
    try:
        delete_tenant_domain(
            db,
            tenant_id=_parse_tenant_id(tenant_id),
            domain_id=_parse_tenant_id(domain_id),
            actor_id=claims.user_id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except TenantNotFoundError:
        raise HTTPException(status_code=404, detail=TENANT_NOT_FOUND_MESSAGE) from None
    except TenantConflictError:
        raise HTTPException(status_code=409, detail=PRIMARY_DOMAIN_MESSAGE) from None
    except TenantActorError:
        raise HTTPException(status_code=403, detail=TENANT_ACTOR_MESSAGE) from None
    except TenantOnboardingError:
        raise HTTPException(status_code=500, detail=TENANT_ONBOARDING_MESSAGE) from None


@router.patch("/tenants/{tenant_id}/status", response_model=TenantResponse)
def update_tenant_status(
    tenant_id: str,
    payload: TenantStatusUpdate,
    claims: PlatformAccessTokenClaims = Depends(get_platform_access_token_claims),
    db: Session = Depends(get_unscoped_db),
):
    from uuid import UUID

    try:
        tenant_uuid = UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=TENANT_NOT_FOUND_MESSAGE) from None
    try:
        return set_tenant_status(
            db,
            tenant_id=tenant_uuid,
            tenant_status=payload.status,
            actor_id=claims.user_id,
        )
    except TenantNotFoundError:
        raise HTTPException(status_code=404, detail=TENANT_NOT_FOUND_MESSAGE) from None
    except TenantActorError:
        raise HTTPException(status_code=403, detail=TENANT_ACTOR_MESSAGE) from None
    except TenantOnboardingError:
        raise HTTPException(status_code=500, detail=TENANT_ONBOARDING_MESSAGE) from None
