from contextlib import contextmanager
from types import MethodType
from typing import Iterator
from uuid import UUID
from weakref import WeakKeyDictionary

from sqlalchemy import event, inspect, text
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session, with_loader_criteria

from app.models.tenant_models import TenantScopedMixin


_SET_POSTGRES_TENANT = text(
    "SELECT set_config('app.current_tenant_id', :tenant_id, true)"
)
_TENANT_BINDINGS: WeakKeyDictionary[Session, UUID] = WeakKeyDictionary()


def _require_uuid(tenant_id: UUID) -> UUID:
    if not isinstance(tenant_id, UUID):
        raise TypeError("tenant_id must be a UUID")
    return tenant_id


def _tenant_scope(session: Session) -> UUID | None:
    tenant_id = _TENANT_BINDINGS.get(session)
    if tenant_id is None and isinstance(session, TenantSession):
        raise RuntimeError("TenantSession is missing internal tenant binding")
    return tenant_id


def _bind_tenant_scope(session: Session, tenant_id: UUID) -> None:
    configured_tenant = _TENANT_BINDINGS.get(session)
    if configured_tenant not in (None, tenant_id):
        raise ValueError("tenant_id does not match session tenant")
    if configured_tenant is None:
        _TENANT_BINDINGS[session] = tenant_id
    session.info["tenant_id"] = tenant_id


def _validate_tenant_object(obj, tenant_id: UUID) -> None:
    if not isinstance(obj, TenantScopedMixin):
        return

    state = inspect(obj)
    object_tenant = state.dict.get("tenant_id")
    if state.transient:
        if object_tenant not in (None, tenant_id):
            raise ValueError("tenant_id does not match session tenant")
    elif object_tenant != tenant_id:
        raise ValueError("tenant_id does not match session tenant")


def _preflight_save_update(session: Session, instances) -> None:
    tenant_id = _tenant_scope(session)
    seen = set()
    for root in instances:
        root_state = inspect(root)
        graph = [(root, root_state)]
        graph.extend(
            (obj, state)
            for obj, _mapper, state, _dict in root_state.mapper.cascade_iterator(
                "save-update", root_state
            )
        )
        for obj, state in graph:
            if state in seen:
                continue
            seen.add(state)
            if state.session is not None and state.session is not session:
                raise InvalidRequestError(
                    "object is already attached to a different Session"
                )
            _validate_tenant_object(obj, tenant_id)


def _scoped_add(session: Session, instance, _warn: bool = True) -> None:
    _preflight_save_update(session, [instance])
    Session.add(session, instance, _warn=_warn)


def _scoped_add_all(session: Session, instances) -> None:
    instances = list(instances)
    _preflight_save_update(session, instances)
    Session.add_all(session, instances)


def _install_scoped_write_methods(session: Session) -> None:
    if not isinstance(session, TenantSession):
        session.add = MethodType(_scoped_add, session)
        session.add_all = MethodType(_scoped_add_all, session)


class TenantSession(Session):
    """A Session explicitly bound to one tenant for ORM operations.

    The authoritative binding is private and immutable; ``Session.info`` is
    only an observational mirror and cannot change the active scope.
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
        _bind_tenant_scope(self, tenant_id)

    def add(self, instance, _warn: bool = True) -> None:
        _scoped_add(self, instance, _warn=_warn)

    def add_all(self, instances) -> None:
        _scoped_add_all(self, instances)

    def get(self, entity, ident, **kwargs):
        tenant_id = _tenant_scope(self)
        instance = super().get(entity, ident, **kwargs)
        if (
            isinstance(instance, TenantScopedMixin)
            and instance.tenant_id != tenant_id
        ):
            return None
        return instance


@event.listens_for(Session, "do_orm_execute")
def add_tenant_filter(execute_state) -> None:
    tenant_id = _tenant_scope(execute_state.session)
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
    tenant_id = _tenant_scope(session)
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
    tenant_id = _tenant_scope(session)
    if tenant_id is not None:
        _validate_tenant_object(obj, tenant_id)


@event.listens_for(Session, "after_begin")
def set_postgres_tenant_on_transaction_begin(session, _transaction, connection) -> None:
    tenant_id = _tenant_scope(session)
    if tenant_id is not None and connection.dialect.name == "postgresql":
        connection.execute(
            _SET_POSTGRES_TENANT,
            {"tenant_id": str(tenant_id)},
        )


def set_tenant_context(db: Session, tenant_id: UUID) -> None:
    """Bind a Session to a tenant and configure its current PostgreSQL transaction."""

    tenant_id = _require_uuid(tenant_id)
    configured_tenant = _TENANT_BINDINGS.get(db)
    if configured_tenant not in (None, tenant_id):
        raise ValueError("tenant_id does not match session tenant")
    if configured_tenant is None and any(
        isinstance(obj, TenantScopedMixin) for obj in db.identity_map.values()
    ):
        raise ValueError(
            "cannot set tenant context after tenant-scoped objects were loaded"
        )
    _install_scoped_write_methods(db)
    _bind_tenant_scope(db, tenant_id)

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
