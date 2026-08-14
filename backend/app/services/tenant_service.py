from uuid import UUID

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.config.tenant_session import (
    TenantCapableSession,
    _release_platform_onboarding_context,
    set_tenant_context,
)
from app.core.security import get_password_hash
from app.models.models import SystemConfig, User, UserRole
from app.models.tenant_models import (
    PlatformAuditLog,
    PlatformUser,
    Tenant,
    TenantStatus,
)
from app.schemas.tenant import (
    TenantAdminPasswordResetRequest,
    TenantAdminResponse,
    TenantDetailResponse,
    TenantOnboardingRequest,
    TenantResponse,
)


class TenantServiceError(Exception):
    """A safe platform-control-plane service error."""


class TenantConflictError(TenantServiceError):
    pass


class TenantActorError(TenantServiceError):
    pass


class TenantOnboardingError(TenantServiceError):
    pass


class TenantNotFoundError(TenantServiceError):
    pass


class TenantAdminNotFoundError(TenantServiceError):
    pass


TENANT_CONFLICT_MESSAGE = "Tenant code already exists"
TENANT_ACTOR_MESSAGE = "Platform actor is not authorized"
TENANT_ONBOARDING_MESSAGE = "Tenant onboarding failed"
TENANT_NOT_FOUND_MESSAGE = "Tenant not found"
TENANT_ADMIN_NOT_FOUND_MESSAGE = "Tenant administrator not found"


def _require_platform_actor(db, actor_id: UUID) -> PlatformUser:
    actor = (
        db.query(PlatformUser)
        .filter(PlatformUser.id == actor_id, PlatformUser.is_active.is_(True))
        .first()
    )
    if actor is None:
        raise TenantActorError(TENANT_ACTOR_MESSAGE)
    return actor


def create_tenant_with_admin(
    db: TenantCapableSession,
    payload: TenantOnboardingRequest,
    *,
    actor_id: UUID,
) -> Tenant:
    """Create all initial tenant records atomically in the supplied Session."""

    bound_tenant_id = None
    try:
        with db.begin():
            actor = (
                db.query(PlatformUser)
                .filter(
                    PlatformUser.id == actor_id,
                    PlatformUser.is_active.is_(True),
                )
                .first()
            )
            if actor is None:
                raise TenantActorError(TENANT_ACTOR_MESSAGE)

            conflict = db.query(Tenant.id).filter(Tenant.code == payload.code).first()
            if conflict is not None:
                raise TenantConflictError(TENANT_CONFLICT_MESSAGE)

            tenant = Tenant(
                code=payload.code,
                name=payload.name,
                status=TenantStatus.ACTIVE,
            )
            db.add(tenant)
            db.flush()
            set_tenant_context(db, tenant.id)
            bound_tenant_id = tenant.id
            system_config = SystemConfig()
            admin = User(
                email=str(payload.admin_email),
                hashed_password=get_password_hash(payload.admin_password),
                role=UserRole.ADMIN,
                is_active=True,
            )
            db.add(system_config)
            db.add(admin)
            db.add(
                PlatformAuditLog(
                    actor_id=actor_id,
                    action="tenant.created",
                    target_tenant_id=tenant.id,
                )
            )
            db.flush()
            db.expunge(system_config)
            db.expunge(admin)
            db.expunge(tenant)
        return tenant
    except (TenantConflictError, TenantActorError):
        raise
    except IntegrityError:
        raise TenantConflictError(TENANT_CONFLICT_MESSAGE) from None
    except Exception:
        raise TenantOnboardingError(TENANT_ONBOARDING_MESSAGE) from None
    finally:
        if bound_tenant_id is not None:
            _release_platform_onboarding_context(db, bound_tenant_id)


def set_tenant_status(
    db: TenantCapableSession,
    *,
    tenant_id: UUID,
    tenant_status: TenantStatus,
    actor_id: UUID,
) -> Tenant:
    try:
        with db.begin():
            actor = (
                db.query(PlatformUser)
                .filter(
                    PlatformUser.id == actor_id,
                    PlatformUser.is_active.is_(True),
                )
                .first()
            )
            if actor is None:
                raise TenantActorError(TENANT_ACTOR_MESSAGE)

            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if tenant is None:
                raise TenantNotFoundError(TENANT_NOT_FOUND_MESSAGE)

            previous_status = tenant.status
            tenant.status = tenant_status
            db.add(
                PlatformAuditLog(
                    actor_id=actor_id,
                    action="tenant.status_changed",
                    target_tenant_id=tenant.id,
                    details={
                        "previous_status": previous_status.value,
                        "status": tenant_status.value,
                    },
                )
            )
            db.flush()
            db.expunge(tenant)
        return tenant
    except (TenantActorError, TenantNotFoundError):
        raise
    except Exception:
        raise TenantOnboardingError(TENANT_ONBOARDING_MESSAGE) from None


def get_tenant_detail(
    db: TenantCapableSession,
    *,
    tenant_id: UUID,
    actor_id: UUID,
) -> TenantDetailResponse:
    bound_tenant_id = None
    try:
        with db.begin():
            _require_platform_actor(db, actor_id)
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if tenant is None:
                raise TenantNotFoundError(TENANT_NOT_FOUND_MESSAGE)
            set_tenant_context(db, tenant_id)
            bound_tenant_id = tenant_id
            admin_rows = (
                db.query(User.id, User.email, User.full_name, User.is_active)
                .filter(
                    User.tenant_id == tenant_id,
                    User.role == UserRole.ADMIN,
                )
                .order_by(User.email)
                .all()
            )
            response = TenantDetailResponse.model_validate(
                {
                    **TenantResponse.model_validate(tenant).model_dump(),
                    "admins": [
                        TenantAdminResponse(
                            id=row.id,
                            email=row.email,
                            full_name=row.full_name,
                            is_active=row.is_active,
                        )
                        for row in admin_rows
                    ],
                }
            )
        return response
    except (TenantActorError, TenantNotFoundError):
        raise
    except Exception:
        raise TenantOnboardingError(TENANT_ONBOARDING_MESSAGE) from None
    finally:
        if bound_tenant_id is not None:
            _release_platform_onboarding_context(db, bound_tenant_id)


def reset_tenant_admin_password(
    db: TenantCapableSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    payload: TenantAdminPasswordResetRequest,
    actor_id: UUID,
) -> None:
    bound_tenant_id = None
    try:
        with db.begin():
            _require_platform_actor(db, actor_id)
            if db.query(Tenant.id).filter(Tenant.id == tenant_id).first() is None:
                raise TenantNotFoundError(TENANT_NOT_FOUND_MESSAGE)
            set_tenant_context(db, tenant_id)
            bound_tenant_id = tenant_id
            password_hash = get_password_hash(payload.new_password)
            target = db.execute(
                update(User)
                .where(
                    User.id == user_id,
                    User.tenant_id == tenant_id,
                    User.role == UserRole.ADMIN,
                )
                .values(
                    hashed_password=password_hash,
                    credential_version=User.credential_version + 1,
                )
                .returning(User.email, User.credential_version)
                .execution_options(synchronize_session=False)
            ).first()
            if target is None:
                raise TenantAdminNotFoundError(TENANT_ADMIN_NOT_FOUND_MESSAGE)
            db.add(
                PlatformAuditLog(
                    actor_id=actor_id,
                    action="tenant.admin_password_reset",
                    target_tenant_id=tenant_id,
                    details={
                        "target_user_id": str(user_id),
                        "target_email": target.email,
                        "credential_version": target.credential_version,
                    },
                )
            )
            db.flush()
    except (
        TenantActorError,
        TenantAdminNotFoundError,
        TenantNotFoundError,
    ):
        raise
    except Exception:
        raise TenantOnboardingError(TENANT_ONBOARDING_MESSAGE) from None
    finally:
        if bound_tenant_id is not None:
            _release_platform_onboarding_context(db, bound_tenant_id)
