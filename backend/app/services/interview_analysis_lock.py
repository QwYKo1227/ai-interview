"""Keep one interview analysis active across request and recovery workers."""

from contextlib import contextmanager
from hashlib import blake2b
from threading import Lock
from uuid import UUID
from weakref import WeakValueDictionary

from sqlalchemy import text


_local_locks = WeakValueDictionary()
_local_locks_guard = Lock()


@contextmanager
def analysis_lock(bind, tenant_id: UUID, interview_id: UUID):
    """Try once; PostgreSQL releases this lock if the worker connection dies.

    Use a dedicated connection so the session lock survives ORM commits and
    cannot leak back into the pool. SQLite development/tests use a local lock.
    """
    identity = f"interview-analysis:{tenant_id}:{interview_id}"
    if bind.dialect.name != "postgresql":
        with _local_locks_guard:
            lock = _local_locks.setdefault(identity, Lock())
        acquired = lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()
        return

    key = int.from_bytes(blake2b(identity.encode(), digest_size=8).digest(), "big", signed=True)
    with bind.connect() as connection:
        acquired = False
        try:
            acquired = connection.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": key},
            ).scalar_one()
            connection.commit()
            yield acquired
        finally:
            if acquired:
                try:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                    connection.commit()
                except Exception:
                    # A connection with an uncertain lock state must not be reused.
                    connection.invalidate()
                    raise
