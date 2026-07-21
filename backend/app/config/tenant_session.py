from contextlib import contextmanager
from typing import Iterator
from uuid import UUID

from sqlalchemy import event, inspect, text
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session, with_loader_criteria

from app.models.tenant_models import TenantScopedMixin


_SET_POSTGRES_TENANT = text(
    "SELECT set_config('app.current_tenant_id', :tenant_id, true)"
)


def _require_uuid(tenant_id: UUID) -> UUID:
    if not isinstance(tenant_id, UUID):
        raise TypeError("tenant_id must be a UUID")
    return tenant_id


class TenantSession(Session):
    """A Session explicitly bound to one tenant for ORM operations.

    ORM SELECTs and loaders are scoped automatically. Raw textual/Core SQL is
    outside this application-layer filter and relies on PostgreSQL RLS once it
    is enabled.
    """

    def __init__(self, *args, tenant_id: UUID | None = None, **kwargs) -> None:
        info = dict(kwargs.pop("info", None) or {})
        configured_tenant = info.get("tenant_id")
        if tenant_id is None:
            tenant_id = configured_tenant
        tenant_id = _require_uuid(tenant_id)
        if configured_tenant not in (None, tenant_id):
            raise ValueError("tenant_id does not match session tenant")
        info["tenant_id"] = tenant_id
        super().__init__(*args, info=info, **kwargs)

    def get(self, entity, ident, **kwargs):
        instance = super().get(entity, ident, **kwargs)
        if (
            isinstance(instance, TenantScopedMixin)
            and instance.tenant_id != self.info["tenant_id"]
        ):
            return None
        return instance


@event.listens_for(Session, "do_orm_execute")
def add_tenant_filter(execute_state) -> None:
    tenant_id = execute_state.session.info.get("tenant_id")
    if tenant_id is None:
        return
    if execute_state.is_from_statement:
        raise InvalidRequestError(
            "textual ORM statements are forbidden in tenant-scoped sessions"
        )
    if execute_state.is_select:
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                TenantScopedMixin,
                lambda model: model.tenant_id == tenant_id,
                include_aliases=True,
            )
        )


@event.listens_for(Session, "before_flush")
def fill_tenant_id(session, _flush_context, _instances) -> None:
    tenant_id = session.info.get("tenant_id")
    if tenant_id is None:
        return
    for obj in session.new:
        if isinstance(obj, TenantScopedMixin):
            if obj.tenant_id not in (None, tenant_id):
                raise ValueError("tenant_id does not match session tenant")
            obj.tenant_id = tenant_id

    for obj in session.dirty.union(session.deleted):
        if isinstance(obj, TenantScopedMixin) and obj.tenant_id != tenant_id:
            raise ValueError("tenant_id does not match session tenant")


@event.listens_for(Session, "before_attach")
def reject_cross_tenant_attach(session, obj) -> None:
    tenant_id = session.info.get("tenant_id")
    state = inspect(obj)
    if (
        tenant_id is not None
        and isinstance(obj, TenantScopedMixin)
        and not state.transient
        and state.dict.get("tenant_id") != tenant_id
    ):
        raise ValueError("tenant_id does not match session tenant")


@event.listens_for(Session, "after_begin")
def set_postgres_tenant_on_transaction_begin(session, _transaction, connection) -> None:
    tenant_id = session.info.get("tenant_id")
    if tenant_id is not None and connection.dialect.name == "postgresql":
        connection.execute(
            _SET_POSTGRES_TENANT,
            {"tenant_id": str(tenant_id)},
        )


def set_tenant_context(db: Session, tenant_id: UUID) -> None:
    """Bind a Session to a tenant and configure its current PostgreSQL transaction."""

    tenant_id = _require_uuid(tenant_id)
    configured_tenant = db.info.get("tenant_id")
    if configured_tenant not in (None, tenant_id):
        raise ValueError("tenant_id does not match session tenant")
    if configured_tenant is None and any(
        isinstance(obj, TenantScopedMixin) for obj in db.identity_map.values()
    ):
        raise ValueError(
            "cannot set tenant context after tenant-scoped objects were loaded"
        )
    db.info["tenant_id"] = tenant_id

    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        db.execute(_SET_POSTGRES_TENANT, {"tenant_id": str(tenant_id)})


@contextmanager
def tenant_session(tenant_id: UUID) -> Iterator[TenantSession]:
    """Open a tenant-bound Session and always release its transaction/connection."""

    tenant_id = _require_uuid(tenant_id)
    from app.config.database import TenantSessionLocal

    db = TenantSessionLocal(tenant_id=tenant_id)
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
