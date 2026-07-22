from fastapi import APIRouter, Depends, HTTPException, Request, status
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
from app.models.tenant_models import PlatformUser
from app.schemas.tenant import (
    PlatformLoginRequest,
    TenantOnboardingRequest,
    TenantResponse,
    TenantStatusUpdate,
)
from app.schemas.user import Token
from app.services.tenant_service import (
    TENANT_ACTOR_MESSAGE,
    TENANT_CONFLICT_MESSAGE,
    TENANT_NOT_FOUND_MESSAGE,
    TENANT_ONBOARDING_MESSAGE,
    TenantActorError,
    TenantConflictError,
    TenantNotFoundError,
    TenantOnboardingError,
    create_tenant_with_admin,
    set_tenant_status,
)


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
    db: Session = Depends(get_unscoped_db),
):
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
