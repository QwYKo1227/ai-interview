from contextlib import contextmanager
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


def _validate_tenant_object(obj, tenant_id: UUID, session: Session) -> None:
    if not isinstance(obj, TenantScopedMixin):
        return

    state = inspect(obj)
    object_tenant = state.dict.get("tenant_id")
    if object_tenant is None and (
        state.transient or (state.pending and state.session is session)
    ):
        obj.tenant_id = tenant_id
    elif object_tenant != tenant_id:
        raise ValueError("tenant_id does not match session tenant")


def _preflight_graph(session: Session, instances, cascade: str) -> None:
    tenant_id = _tenant_scope(session)
    seen = set()
    for root in instances:
        root_state = inspect(root)
        graph = [(root, root_state)]
        graph.extend(
            (obj, state)
            for obj, _mapper, state, _dict in root_state.mapper.cascade_iterator(
                cascade, root_state
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
            _validate_tenant_object(obj, tenant_id, session)


def _scoped_add(session: Session, instance, _warn: bool = True) -> None:
    _preflight_graph(session, [instance], "save-update")
    Session.add(session, instance, _warn=_warn)


def _scoped_add_all(session: Session, instances) -> None:
    instances = list(instances)
    _preflight_graph(session, instances, "save-update")
    Session.add_all(session, instances)


def _scoped_merge(session: Session, instance, *, load: bool = True, options=None):
    _tenant_scope(session)
    raise InvalidRequestError("merge() is disabled for tenant-scoped sessions")


class TenantCapableSession(Session):
    """A Session that can be safely bound to a tenant after construction."""

    def add(self, instance, _warn: bool = True) -> None:
        if _tenant_scope(self) is None:
            return super().add(instance, _warn=_warn)
        return _scoped_add(self, instance, _warn=_warn)

    def add_all(self, instances) -> None:
        if _tenant_scope(self) is None:
            return super().add_all(instances)
        return _scoped_add_all(self, instances)

    def merge(self, instance, *, load: bool = True, options=None):
        if _tenant_scope(self) is None:
            return super().merge(instance, load=load, options=options)
        return _scoped_merge(self, instance, load=load, options=options)


class TenantSession(TenantCapableSession):
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

    def get(self, entity, ident, **kwargs):
        tenant_id = _tenant_scope(self)
        instance = super().get(entity, ident, **kwargs)
        if (
            isinstance(instance, TenantScopedMixin)
            and instance.tenant_id != tenant_id
        ):
            return None
        return instance


_SAFE_TENANT_SESSION_TYPES = {TenantCapableSession, TenantSession}


def _register_tenant_session_factory_type(session_type: type[Session]) -> None:
    """Register a sessionmaker-generated class after proving it has no overrides."""

    if len(session_type.__bases__) != 1 or session_type.__bases__[0] not in (
        TenantCapableSession,
        TenantSession,
    ):
        raise TypeError("tenant session factory class has an unsafe base")
    if any(
        method_name in session_type.__dict__
        for method_name in ("add", "add_all", "merge", "get")
    ):
        raise TypeError("tenant session factory class overrides protected methods")
    _SAFE_TENANT_SESSION_TYPES.add(session_type)


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
        _validate_tenant_object(obj, tenant_id, session)


@event.listens_for(Session, "after_begin")
def set_postgres_tenant_on_transaction_begin(session, _transaction, connection) -> None:
    tenant_id = _tenant_scope(session)
    if tenant_id is not None and connection.dialect.name == "postgresql":
        connection.execute(
            _SET_POSTGRES_TENANT,
            {"tenant_id": str(tenant_id)},
        )


def set_tenant_context(db: TenantCapableSession, tenant_id: UUID) -> None:
    """Bind a Session to a tenant and configure its current PostgreSQL transaction."""

    if type(db) not in _SAFE_TENANT_SESSION_TYPES:
        raise TypeError(
            "set_tenant_context requires an exact TenantCapableSession "
            "or TenantSession"
        )
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
