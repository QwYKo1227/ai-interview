from uuid import UUID

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
    TenantDomain,
    TenantStatus,
)
from app.schemas.tenant import TenantOnboardingRequest


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


TENANT_CONFLICT_MESSAGE = "Tenant code or domain already exists"
TENANT_ACTOR_MESSAGE = "Platform actor is not authorized"
TENANT_ONBOARDING_MESSAGE = "Tenant onboarding failed"
TENANT_NOT_FOUND_MESSAGE = "Tenant not found"


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

            conflict = (
                db.query(Tenant.id)
                .filter(Tenant.code == payload.code)
                .first()
                or db.query(TenantDomain.id)
                .filter(TenantDomain.domain == payload.primary_domain)
                .first()
            )
            if conflict is not None:
                raise TenantConflictError(TENANT_CONFLICT_MESSAGE)

            tenant = Tenant(
                code=payload.code,
                name=payload.name,
                status=TenantStatus.ACTIVE,
            )
            db.add(tenant)
            db.flush()
            db.add(
                TenantDomain(
                    tenant_id=tenant.id,
                    domain=payload.primary_domain,
                    is_primary=True,
                )
            )

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
            tenant.primary_domain = payload.primary_domain
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
            tenant.primary_domain = (
                db.query(TenantDomain.domain)
                .filter(
                    TenantDomain.tenant_id == tenant.id,
                    TenantDomain.is_primary.is_(True),
                )
                .scalar()
            )
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
