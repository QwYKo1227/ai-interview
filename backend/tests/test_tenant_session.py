from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session, object_session, sessionmaker


class PreGuardSession(Session):
    def add(self, instance, _warn=True):
        return Session.add(self, instance, _warn=_warn)


from app.config import database
from app.config.database import get_unscoped_db
from app.config.tenant_session import (
    TenantCapableSession,
    TenantSession,
    set_tenant_context,
    tenant_session,
)
from app.core.tenant_context import TenantContext
from app.models.models import Position, Resume


class OverridingTenantCapableSession(TenantCapableSession):
    def add(self, instance, _warn=True):
        return Session.add(self, instance, _warn=_warn)


@pytest.fixture
def tenant_session_factory(db):
    session_factory = sessionmaker(
        bind=db.get_bind(),
        class_=TenantSession,
        autoflush=False,
        expire_on_commit=False,
    )

    @contextmanager
    def open_session(tenant_id):
        session = session_factory(tenant_id=tenant_id)
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return open_session


@contextmanager
def _scoped_session(session_kind, bind, tenant_id):
    if session_kind == "tenant":
        session = TenantSession(bind=bind, tenant_id=tenant_id, autoflush=False)
    else:
        session = TenantCapableSession(bind=bind, autoflush=False)
        set_tenant_context(session, tenant_id)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_tenant_context_contains_only_trusted_tenant_metadata():
    tenant_id = uuid4()

    context = TenantContext(
        tenant_id=tenant_id,
        tenant_code="careray",
        source="jwt",
    )

    assert context.tenant_id == tenant_id
    assert context.tenant_code == "careray"
    assert context.source == "jwt"


def test_tenant_session_requires_explicit_uuid_tenant_id(db):
    session_factory = sessionmaker(bind=db.get_bind(), class_=TenantSession)

    with pytest.raises(TypeError, match="tenant_id"):
        session_factory()

    with pytest.raises(TypeError, match="UUID"):
        session_factory(tenant_id="user-controlled-tenant-id")


def test_tenant_session_can_take_explicit_tenant_id_from_session_info(db, tenant_a):
    session_factory = sessionmaker(bind=db.get_bind(), class_=TenantSession)

    with session_factory(info={"tenant_id": tenant_a.id}) as tenant_db:
        assert tenant_db.info["tenant_id"] == tenant_a.id


def test_mutating_or_removing_session_info_cannot_change_tenant_scope(
    db, tenant_session_factory, tenant_a, tenant_b
):
    db.add_all(
        [
            Position(tenant_id=tenant_a.id, title="A", description="A"),
            Position(tenant_id=tenant_b.id, title="B", description="B"),
        ]
    )
    db.commit()

    with tenant_session_factory(tenant_a.id) as tenant_db:
        assert [position.title for position in tenant_db.query(Position).all()] == ["A"]

        tenant_db.info["tenant_id"] = tenant_b.id
        assert [position.title for position in tenant_db.query(Position).all()] == ["A"]

        tenant_db.info.pop("tenant_id")
        assert [position.title for position in tenant_db.query(Position).all()] == ["A"]


def test_plain_session_info_cannot_enable_tenant_scope(db, tenant_a, tenant_b):
    db.add_all(
        [
            Position(tenant_id=tenant_a.id, title="A", description="A"),
            Position(tenant_id=tenant_b.id, title="B", description="B"),
        ]
    )
    db.commit()

    plain_db = Session(bind=db.get_bind(), info={"tenant_id": tenant_a.id})
    try:
        assert {position.title for position in plain_db.query(Position).all()} == {
            "A",
            "B",
        }
    finally:
        plain_db.close()


def test_tenant_capable_session_is_a_dedicated_session_class():
    assert TenantCapableSession is not Session
    assert issubclass(TenantCapableSession, Session)


@pytest.mark.parametrize(
    "session_class",
    [Session, PreGuardSession, OverridingTenantCapableSession],
)
def test_set_tenant_context_rejects_sessions_without_exact_safe_type(
    session_class, db, tenant_a
):
    unsafe_db = session_class(bind=db.get_bind())
    try:
        with pytest.raises(TypeError, match="TenantCapableSession"):
            set_tenant_context(unsafe_db, tenant_a.id)

        assert "tenant_id" not in unsafe_db.info
    finally:
        unsafe_db.close()


def test_database_session_factory_uses_exact_tenant_capable_session_type():
    factory_db = database.SessionLocal()
    try:
        assert type(factory_db) is database.SessionLocal.class_
        assert type(factory_db).__bases__ == (TenantCapableSession,)
        assert not any(
            method_name in type(factory_db).__dict__
            for method_name in ("add", "add_all", "merge", "get")
        )
        set_tenant_context(factory_db, uuid4())
    finally:
        factory_db.close()


def test_set_tenant_context_cannot_rebind_even_if_info_is_tampered(
    db, tenant_a, tenant_b
):
    tenant_db = TenantCapableSession(bind=db.get_bind())
    try:
        set_tenant_context(tenant_db, tenant_a.id)
        set_tenant_context(tenant_db, tenant_a.id)
        tenant_db.info["tenant_id"] = tenant_b.id

        with pytest.raises(ValueError, match="does not match session tenant"):
            set_tenant_context(tenant_db, tenant_b.id)
    finally:
        tenant_db.close()


def test_tenant_session_without_internal_binding_fails_closed(db):
    tenant_db = TenantSession.__new__(TenantSession)
    Session.__init__(tenant_db, bind=db.get_bind())
    try:
        with pytest.raises(RuntimeError, match="missing internal tenant binding"):
            tenant_db.query(Position).all()
    finally:
        tenant_db.close()


def test_tenant_session_only_reads_own_rows(tenant_session_factory, tenant_a, tenant_b):
    with tenant_session_factory(tenant_a.id) as db:
        db.add(Position(title="A", description="A"))
        db.commit()
    with tenant_session_factory(tenant_b.id) as db:
        db.add(Position(title="B", description="B"))
        db.commit()

    with tenant_session_factory(tenant_a.id) as db:
        assert [position.title for position in db.query(Position).all()] == ["A"]


def test_new_row_gets_tenant_id_automatically(tenant_session_factory, tenant_a):
    with tenant_session_factory(tenant_a.id) as db:
        position = Position(title="A", description="A")
        db.add(position)
        db.commit()

        assert position.tenant_id == tenant_a.id


def test_new_row_with_different_tenant_id_is_rejected(
    tenant_session_factory, tenant_a, tenant_b
):
    with tenant_session_factory(tenant_a.id) as db:
        with pytest.raises(ValueError, match="does not match session tenant"):
            db.add(
                Position(
                    tenant_id=tenant_b.id,
                    title="Cross-tenant",
                    description="must fail",
                )
            )
            db.flush()


def test_session_get_hides_another_tenants_known_id(
    tenant_session_factory, tenant_a, tenant_b
):
    with tenant_session_factory(tenant_b.id) as db:
        position = Position(title="B", description="B")
        db.add(position)
        db.commit()
        position_id = position.id

    with tenant_session_factory(tenant_a.id) as db:
        assert db.get(Position, position_id) is None


def test_lazy_relationship_loader_cannot_read_another_tenant(
    db, tenant_session_factory, tenant_a, tenant_b
):
    foreign_position = Position(
        tenant_id=tenant_b.id,
        title="B",
        description="B",
    )
    db.add(foreign_position)
    db.commit()

    resume = Resume(
        tenant_id=tenant_a.id,
        candidate_name="Candidate A",
        position_id=foreign_position.id,
    )
    db.add(resume)
    db.commit()
    tenant_a_id = tenant_a.id
    resume_id = resume.id
    db.expunge_all()

    with tenant_session_factory(tenant_a_id) as tenant_db:
        loaded_resume = tenant_db.get(Resume, resume_id)

        assert loaded_resume is not None
        assert loaded_resume.position is None


def test_textual_orm_statement_is_rejected_before_it_can_poison_identity_map(
    tenant_session_factory, tenant_a, tenant_b
):
    with tenant_session_factory(tenant_a.id) as tenant_db:
        tenant_db.add(Position(title="A", description="A"))
        tenant_db.commit()
    with tenant_session_factory(tenant_b.id) as tenant_db:
        tenant_db.add(Position(title="B", description="B"))
        tenant_db.commit()

    with tenant_session_factory(tenant_a.id) as tenant_db:
        with pytest.raises(InvalidRequestError, match="textual ORM statements"):
            tenant_db.query(Position).from_statement(
                text("SELECT * FROM positions")
            ).all()


def test_set_tenant_context_scopes_a_plain_session(db, tenant_a, tenant_b):
    db.add_all(
        [
            Position(tenant_id=tenant_a.id, title="A", description="A"),
            Position(tenant_id=tenant_b.id, title="B", description="B"),
        ]
    )
    db.commit()

    tenant_db = TenantCapableSession(bind=db.get_bind())
    try:
        set_tenant_context(tenant_db, tenant_a.id)

        assert [position.title for position in tenant_db.query(Position).all()] == ["A"]
    finally:
        tenant_db.close()


def test_set_tenant_context_rejects_a_session_with_tenant_objects_already_loaded(
    db, tenant_a, tenant_b
):
    db.add(Position(tenant_id=tenant_b.id, title="B", description="B"))
    db.commit()

    tenant_db = TenantCapableSession(bind=db.get_bind())
    try:
        loaded_position = tenant_db.query(Position).one()
        assert loaded_position.tenant_id == tenant_b.id

        with pytest.raises(ValueError, match="tenant-scoped objects"):
            set_tenant_context(tenant_db, tenant_a.id)
    finally:
        tenant_db.close()


def test_attaching_existing_object_from_another_tenant_is_rejected(
    db, tenant_session_factory, tenant_a, tenant_b
):
    foreign_position = Position(
        tenant_id=tenant_b.id,
        title="B",
        description="B",
    )
    db.add(foreign_position)
    db.commit()
    db.expunge(foreign_position)

    with tenant_session_factory(tenant_a.id) as tenant_db:
        with pytest.raises(ValueError, match="does not match session tenant"):
            tenant_db.add(foreign_position)
        assert object_session(foreign_position) is None
        assert foreign_position not in tenant_db.identity_map.values()


def test_failed_cascade_attach_leaves_root_and_foreign_objects_unbound(
    db, tenant_session_factory, tenant_a, tenant_b
):
    foreign_position = Position(
        tenant_id=tenant_b.id,
        title="B",
        description="B",
    )
    legitimate_position = Position(
        tenant_id=tenant_a.id,
        title="A",
        description="A",
    )
    db.add_all([foreign_position, legitimate_position])
    db.commit()
    foreign_position.tenant_id
    db.expunge(foreign_position)
    resume = Resume(candidate_name="Candidate A", position=foreign_position)

    with tenant_session_factory(tenant_a.id) as tenant_db:
        legitimate = tenant_db.get(Position, legitimate_position.id)
        new_before = set(tenant_db.new)

        with pytest.raises(ValueError, match="does not match session tenant"):
            tenant_db.add(resume)

        assert object_session(legitimate) is tenant_db
        assert object_session(resume) is None
        assert object_session(foreign_position) is None
        assert set(tenant_db.new) == new_before


def test_failed_add_all_preflight_is_atomic(
    db, tenant_session_factory, tenant_a, tenant_b
):
    foreign_position = Position(
        tenant_id=tenant_b.id,
        title="B",
        description="B",
    )
    db.add(foreign_position)
    db.commit()
    foreign_position.tenant_id
    db.expunge(foreign_position)
    valid_root = Position(title="A", description="A")
    invalid_root = Resume(candidate_name="Candidate A", position=foreign_position)

    with tenant_session_factory(tenant_a.id) as tenant_db:
        new_before = set(tenant_db.new)

        with pytest.raises(ValueError, match="does not match session tenant"):
            tenant_db.add_all([valid_root, invalid_root])

        assert object_session(valid_root) is None
        assert object_session(invalid_root) is None
        assert object_session(foreign_position) is None
        assert set(tenant_db.new) == new_before


@pytest.mark.parametrize("operation", ["add", "add_all"])
def test_plain_scoped_session_attach_preflight_is_atomic(
    operation, db, tenant_a, tenant_b
):
    foreign_position = Position(
        tenant_id=tenant_b.id,
        title="B",
        description="B",
    )
    db.add(foreign_position)
    db.commit()
    foreign_position.tenant_id
    db.expunge(foreign_position)
    invalid_root = Resume(candidate_name="Candidate A", position=foreign_position)
    valid_root = Position(title="A", description="A")

    tenant_db = TenantCapableSession(bind=db.get_bind())
    try:
        set_tenant_context(tenant_db, tenant_a.id)
        new_before = set(tenant_db.new)

        with pytest.raises(ValueError, match="does not match session tenant"):
            if operation == "add":
                tenant_db.add(invalid_root)
            else:
                tenant_db.add_all([valid_root, invalid_root])

        assert object_session(invalid_root) is None
        assert object_session(foreign_position) is None
        assert object_session(valid_root) is None
        assert set(tenant_db.new) == new_before
    finally:
        tenant_db.close()


@pytest.mark.parametrize("operation", ["add", "add_all", "merge"])
def test_cached_plain_session_write_method_enforces_scope_without_residue(
    operation, db, tenant_a, tenant_b
):
    foreign_position = Position(
        tenant_id=tenant_b.id,
        title="B",
        description="B",
    )
    db.add(foreign_position)
    db.commit()
    foreign_position.tenant_id
    db.expunge(foreign_position)
    invalid_root = Resume(candidate_name="Candidate A", position=foreign_position)
    valid_root = Position(title="A", description="A")

    tenant_db = TenantCapableSession(bind=db.get_bind())
    try:
        cached_method = getattr(tenant_db, operation)
        set_tenant_context(tenant_db, tenant_a.id)
        new_before = set(tenant_db.new)
        identity_before = set(tenant_db.identity_map.values())

        expected_error = InvalidRequestError if operation == "merge" else ValueError
        expected_message = "disabled" if operation == "merge" else "session tenant"
        with pytest.raises(expected_error, match=expected_message):
            if operation == "add":
                cached_method(invalid_root)
            elif operation == "add_all":
                cached_method([valid_root, invalid_root])
            else:
                cached_method(foreign_position, load=True)

        assert set(tenant_db.new) == new_before
        assert set(tenant_db.identity_map.values()) == identity_before
        assert object_session(valid_root) is None
        assert object_session(invalid_root) is None
        assert object_session(foreign_position) is None
    finally:
        tenant_db.rollback()
        tenant_db.close()


def test_cached_plain_session_add_accepts_legal_object_after_binding(db, tenant_a):
    tenant_db = TenantCapableSession(bind=db.get_bind())
    try:
        cached_add = tenant_db.add
        set_tenant_context(tenant_db, tenant_a.id)
        position = Position(title="A", description="A")

        cached_add(position)

        assert object_session(position) is tenant_db
        assert position in tenant_db.new
        assert position.tenant_id == tenant_a.id
    finally:
        tenant_db.rollback()
        tenant_db.close()


def test_cached_plain_session_merge_is_disabled_after_binding(db, tenant_a):
    position = Position(
        tenant_id=tenant_a.id,
        title="A",
        description="A",
    )
    db.add(position)
    db.commit()
    position.tenant_id
    db.expunge(position)

    tenant_db = TenantCapableSession(bind=db.get_bind())
    try:
        cached_merge = tenant_db.merge
        set_tenant_context(tenant_db, tenant_a.id)
        new_before = set(tenant_db.new)
        identity_before = set(tenant_db.identity_map.values())

        with pytest.raises(InvalidRequestError, match="disabled"):
            cached_merge(position, load=True)

        assert set(tenant_db.new) == new_before
        assert set(tenant_db.identity_map.values()) == identity_before
        assert object_session(position) is None
    finally:
        tenant_db.rollback()
        tenant_db.close()


def test_cached_write_methods_keep_unscoped_plain_session_native_semantics(
    db, tenant_a
):
    unscoped_db = Session(bind=db.get_bind())
    try:
        cached_add = unscoped_db.add
        cached_add_all = unscoped_db.add_all
        cached_merge = unscoped_db.merge
        first = Position(
            tenant_id=tenant_a.id,
            title="First",
            description="A",
        )
        second = Position(
            tenant_id=tenant_a.id,
            title="Second",
            description="A",
        )

        cached_add(first)
        cached_add_all([second])
        unscoped_db.flush()
        unscoped_db.expunge(first)
        first.title = "Updated"
        merged = cached_merge(first, load=True)

        assert object_session(second) is unscoped_db
        assert merged is not first
        assert merged.title == "Updated"
        assert merged.tenant_id == tenant_a.id
    finally:
        unscoped_db.rollback()
        unscoped_db.close()


def test_sqlalchemy_session_write_methods_are_not_globally_replaced():
    for method in (Session.add, Session.add_all, Session.merge):
        assert not getattr(method, "_tenant_scope_guard", False)


@pytest.mark.parametrize("session_kind", ["tenant", "plain"])
def test_repeated_add_of_pending_object_is_idempotent(
    session_kind, db, tenant_a
):
    position = Position(title="A", description="A")

    with _scoped_session(session_kind, db.get_bind(), tenant_a.id) as tenant_db:
        tenant_db.add(position)
        tenant_db.add(position)

        assert object_session(position) is tenant_db
        assert position in tenant_db.new
        assert position.tenant_id == tenant_a.id


@pytest.mark.parametrize("session_kind", ["tenant", "plain"])
def test_shared_pending_child_can_be_reused_by_another_legal_root(
    session_kind, db, tenant_a
):
    shared_position = Position(title="A", description="A")
    first_resume = Resume(candidate_name="First", position=shared_position)
    second_resume = Resume(candidate_name="Second", position=shared_position)

    with _scoped_session(session_kind, db.get_bind(), tenant_a.id) as tenant_db:
        tenant_db.add(first_resume)
        tenant_db.add(second_resume)

        assert {first_resume, second_resume, shared_position}.issubset(tenant_db.new)
        assert shared_position.tenant_id == tenant_a.id


@pytest.mark.parametrize("session_kind", ["tenant", "plain"])
def test_merge_rejects_cross_tenant_graph_without_session_residue(
    session_kind, db, tenant_a, tenant_b
):
    foreign_position = Position(
        tenant_id=tenant_b.id,
        title="B",
        description="B",
    )
    foreign_resume = Resume(
        tenant_id=tenant_b.id,
        candidate_name="Candidate B",
        position=foreign_position,
    )
    db.add_all([foreign_position, foreign_resume])
    db.commit()
    foreign_resume.tenant_id
    foreign_resume.position.tenant_id
    tenant_a_id = tenant_a.id
    db.expunge_all()

    with _scoped_session(session_kind, db.get_bind(), tenant_a_id) as tenant_db:
        new_before = set(tenant_db.new)
        identity_before = set(tenant_db.identity_map.values())

        with pytest.raises(InvalidRequestError, match="disabled"):
            tenant_db.merge(foreign_resume, load=True)

        assert set(tenant_db.new) == new_before
        assert set(tenant_db.identity_map.values()) == identity_before
        assert object_session(foreign_resume) is None
        assert object_session(foreign_position) is None


@pytest.mark.parametrize("session_kind", ["tenant", "plain"])
@pytest.mark.parametrize("load", [True, False])
def test_scoped_merge_is_rejected_without_side_effects(
    session_kind, load, db, tenant_a
):
    position = Position(
        tenant_id=tenant_a.id,
        title="Original",
        description="A",
    )
    db.add(position)
    db.commit()
    position.tenant_id
    db.expunge(position)
    position.title = "Updated"

    with _scoped_session(session_kind, db.get_bind(), tenant_a.id) as tenant_db:
        new_before = set(tenant_db.new)
        identity_before = set(tenant_db.identity_map.values())

        with pytest.raises(InvalidRequestError, match="disabled"):
            tenant_db.merge(position, load=load)

        assert set(tenant_db.new) == new_before
        assert set(tenant_db.identity_map.values()) == identity_before
        assert object_session(position) is None


def test_unscoped_plain_session_keeps_native_merge_behavior(db, tenant_a):
    position = Position(
        tenant_id=tenant_a.id,
        title="Original",
        description="A",
    )
    db.add(position)
    db.commit()
    position.tenant_id
    db.expunge(position)
    position.title = "Updated"

    unscoped_db = Session(bind=db.get_bind())
    try:
        merged = unscoped_db.merge(position, load=True)

        assert merged.title == "Updated"
        assert merged.tenant_id == tenant_a.id
    finally:
        unscoped_db.rollback()
        unscoped_db.close()


@pytest.mark.parametrize("session_kind", ["tenant", "plain"])
@pytest.mark.parametrize("reentrant_operation", ["add", "merge"])
def test_scoped_merge_cannot_leak_authorization_to_reentrant_operations(
    session_kind, reentrant_operation, db, tenant_a, tenant_b
):
    foreign_position = Position(
        tenant_id=tenant_b.id,
        title="B",
        description="B",
    )
    db.add(foreign_position)
    db.commit()
    foreign_id = foreign_position.id
    db.expire(foreign_position, ["tenant_id"])
    db.expunge(foreign_position)
    assert "tenant_id" not in inspect(foreign_position).dict
    outer_source = Position(title="Outer", description="Outer")

    with _scoped_session(session_kind, db.get_bind(), tenant_a.id) as tenant_db:
        tenant_db.add(Position(title="Pending", description="Pending"))
        callback_entered = []

        def reenter(session, _flush_context, _instances):
            callback_entered.append(True)
            if reentrant_operation == "add":
                session.add(foreign_position)
            else:
                session.merge(foreign_position, load=True)

        event.listen(tenant_db, "before_flush", reenter, once=True)

        with pytest.raises(InvalidRequestError, match="disabled"):
            tenant_db.merge(outer_source, load=True)

        assert callback_entered == []
        assert object_session(foreign_position) is None
        assert "tenant_id" not in inspect(foreign_position).dict

    db.expire_all()
    assert db.get(Position, foreign_id).tenant_id == tenant_b.id


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_dirty_or_deleted_object_cannot_change_to_another_tenant(
    operation, tenant_session_factory, tenant_a, tenant_b
):
    with tenant_session_factory(tenant_a.id) as tenant_db:
        position = Position(title="A", description="A")
        tenant_db.add(position)
        tenant_db.commit()

        position.tenant_id = tenant_b.id
        if operation == "update":
            position.title = "tampered"
        else:
            tenant_db.delete(position)

        with pytest.raises(ValueError, match="does not match session tenant"):
            tenant_db.flush()


def test_same_session_factory_does_not_leak_tenant_data(
    tenant_session_factory, tenant_a, tenant_b
):
    with tenant_session_factory(tenant_a.id) as first:
        first.add(Position(title="A", description="A"))
        first.commit()
        assert first.info["tenant_id"] == tenant_a.id

    with tenant_session_factory(tenant_b.id) as second:
        second.add(Position(title="B", description="B"))
        second.commit()
        assert second.info["tenant_id"] == tenant_b.id
        assert [position.title for position in second.query(Position).all()] == ["B"]


def test_set_tenant_context_skips_postgres_sql_on_sqlite(db, tenant_a):
    tenant_db = TenantSession(bind=db.get_bind(), tenant_id=tenant_a.id)
    try:
        set_tenant_context(tenant_db, tenant_a.id)

        assert tenant_db.info["tenant_id"] == tenant_a.id
        assert not tenant_db.in_transaction()
    finally:
        tenant_db.close()


def test_postgres_tenant_setting_is_transaction_local_and_rebound_per_session():
    engine = create_engine("sqlite://")
    engine.dialect.name = "postgresql"
    set_config_calls = []

    @event.listens_for(engine, "before_cursor_execute", retval=True)
    def replace_postgres_set_config(
        _connection, _cursor, statement, parameters, _context, _executemany
    ):
        if "set_config('app.current_tenant_id'" in statement:
            set_config_calls.append((statement, parameters))
            return "SELECT 1", ()
        return statement, parameters

    session_factory = sessionmaker(bind=engine, class_=TenantSession)
    tenant_a_id = uuid4()
    tenant_b_id = uuid4()

    with session_factory(tenant_id=tenant_a_id) as tenant_db:
        tenant_db.execute(select(1))
        tenant_db.commit()
    with session_factory(tenant_id=tenant_b_id) as tenant_db:
        tenant_db.execute(select(1))
        tenant_db.commit()

    assert len(set_config_calls) == 2
    assert [parameters[0] for _, parameters in set_config_calls] == [
        str(tenant_a_id),
        str(tenant_b_id),
    ]
    assert all(", true)" in statement for statement, _ in set_config_calls)


def test_tenant_session_rolls_back_and_releases_connection_on_exception(
    db, monkeypatch, tenant_a
):
    session_factory = sessionmaker(
        bind=db.get_bind(),
        class_=TenantSession,
        autoflush=False,
        expire_on_commit=False,
        close_resets_only=False,
    )
    monkeypatch.setattr(database, "TenantSessionLocal", session_factory)
    opened_session = None

    with pytest.raises(RuntimeError, match="boom"):
        with tenant_session(tenant_a.id) as tenant_db:
            opened_session = tenant_db
            tenant_db.add(Position(title="uncommitted", description="uncommitted"))
            tenant_db.flush()
            raise RuntimeError("boom")

    assert opened_session is not None
    assert not opened_session.in_transaction()
    with pytest.raises(InvalidRequestError, match="permanently closed"):
        opened_session.connection()
    assert db.query(Position).filter(Position.title == "uncommitted").first() is None


def test_tenant_session_normal_exit_rolls_back_uncommitted_work(
    db, monkeypatch, tenant_a
):
    session_factory = sessionmaker(
        bind=db.get_bind(),
        class_=TenantSession,
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(database, "TenantSessionLocal", session_factory)

    with tenant_session(tenant_a.id) as tenant_db:
        tenant_db.add(Position(title="not committed", description="not committed"))
        tenant_db.flush()

    assert db.query(Position).filter(Position.title == "not committed").first() is None


def test_unscoped_dependency_is_explicitly_documented_for_global_tables_only():
    assert "global tables only" in get_unscoped_db.__doc__.lower()
    assert "tenant business" in get_unscoped_db.__doc__.lower()
