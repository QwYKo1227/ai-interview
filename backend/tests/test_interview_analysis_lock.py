import os
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

from app.services.interview_analysis_lock import analysis_lock


def test_local_lock_releases_after_failure_and_keeps_interviews_independent():
    engine = create_engine("sqlite://")
    tenant_id, interview_id = uuid4(), uuid4()
    try:
        with pytest.raises(RuntimeError):
            with analysis_lock(engine, tenant_id, interview_id) as acquired:
                assert acquired
                with analysis_lock(engine, tenant_id, interview_id) as duplicate:
                    assert not duplicate
                with analysis_lock(engine, tenant_id, uuid4()) as unrelated:
                    assert unrelated
                raise RuntimeError("worker failed")
        with analysis_lock(engine, tenant_id, interview_id) as recovered:
            assert recovered
    finally:
        engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_ANALYSIS_LOCK_DATABASE_URL"), reason="requires isolated PostgreSQL")
def test_postgres_lock_excludes_another_process_and_releases_after_failure():
    engine = create_engine(os.environ["TEST_ANALYSIS_LOCK_DATABASE_URL"])
    tenant_id, interview_id = uuid4(), uuid4()
    script = """
import os, sys
from uuid import UUID
from sqlalchemy import create_engine
from app.services.interview_analysis_lock import analysis_lock
engine = create_engine(os.environ['TEST_ANALYSIS_LOCK_DATABASE_URL'])
try:
    with analysis_lock(engine, UUID(sys.argv[1]), UUID(sys.argv[2])) as acquired:
        print('acquired' if acquired else 'busy')
finally:
    engine.dispose()
"""

    def other_worker(target):
        result = subprocess.run(
            [sys.executable, "-c", script, str(tenant_id), str(target)],
            capture_output=True, text=True, check=True, timeout=15,
        )
        return result.stdout.strip()

    try:
        with pytest.raises(RuntimeError):
            with analysis_lock(engine, tenant_id, interview_id) as acquired:
                assert acquired
                assert other_worker(interview_id) == "busy"
                assert other_worker(uuid4()) == "acquired"
                raise RuntimeError("worker failed")
        assert other_worker(interview_id) == "acquired"
    finally:
        engine.dispose()
