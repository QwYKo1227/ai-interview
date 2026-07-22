import ast
import inspect
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.services import (
    coding_test_ai_service,
    coding_test_service,
    interview_service,
    resume_service,
)


BACKGROUND_FUNCTIONS = [
    resume_service.process_resume_background,
    resume_service.process_resume_task,
    resume_service.on_resume_parse_failure,
    interview_service.generate_questions_background,
    interview_service.send_interview_invitation_background,
    interview_service.generate_evaluation_background,
    interview_service.generate_combined_evaluation,
    interview_service.send_result_notification_background,
    coding_test_ai_service.generate_coding_evaluation_background,
    coding_test_service.evaluate_essay_answers_background,
    coding_test_service.generate_questions_background,
]


@pytest.mark.parametrize("task", BACKGROUND_FUNCTIONS, ids=lambda func: func.__name__)
def test_every_background_function_starts_with_tenant_uuid(task):
    parameters = list(inspect.signature(task).parameters.values())
    assert parameters[0].name == "tenant_id"
    assert parameters[0].annotation in (UUID, "UUID")


def test_background_service_modules_do_not_open_raw_sessions():
    service_dir = Path(__file__).parents[1] / "app" / "services"
    for filename in (
        "resume_service.py",
        "interview_service.py",
        "coding_test_service.py",
        "coding_test_ai_service.py",
        "ai_service.py",
    ):
        tree = ast.parse((service_dir / filename).read_text(encoding="utf-8"))
        assert not [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "SessionLocal"
        ], filename


def test_every_background_enqueue_passes_tenant_before_resource_id():
    app_dir = Path(__file__).parents[1] / "app"
    failures = []
    for path in app_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_task"
        ):
            if len(call.args) < 3:
                failures.append(f"{path.name}:{call.lineno}: missing tenant/resource arguments")
                continue
            tenant_arg = ast.unparse(call.args[1])
            if "tenant" not in tenant_arg:
                failures.append(f"{path.name}:{call.lineno}: first argument is {tenant_arg}")
    assert failures == []


def test_resume_worker_cannot_read_another_tenants_resource(db, tenant_a, tenant_b, test_resume, monkeypatch):
    seen = []

    class BoundSession:
        def __init__(self, tenant_id):
            from app.config.tenant_session import TenantSession

            self.session = TenantSession(bind=db.get_bind(), tenant_id=tenant_id)

        def __enter__(self):
            return self.session

        def __exit__(self, *_args):
            self.session.close()

    monkeypatch.setattr(resume_service, "tenant_session", BoundSession)
    monkeypatch.setattr(resume_service, "read_file_content", lambda _path: seen.append("read"))

    resume_service.process_resume_task(
        tenant_b.id,
        {"resume_id": test_resume.id, "position_id": test_resume.position_id},
    )

    assert seen == []


def test_resume_enqueue_places_tenant_and_resource_first(monkeypatch):
    submitted = {}

    class Queue:
        def submit(self, **kwargs):
            submitted.update(kwargs)

    monkeypatch.setattr(resume_service, "get_task_queue", lambda: Queue())
    tenant_id, resume_id, position_id = uuid4(), uuid4(), uuid4()

    resume_service.process_resume_background(tenant_id, resume_id, position_id)

    assert submitted["payload"]["tenant_id"] == tenant_id
    assert submitted["payload"]["resume_id"] == resume_id


def test_background_exception_rolls_back_and_closes_tenant_session(monkeypatch):
    lifecycle = {"rollback": False, "close": False}

    class BrokenSession:
        def query(self, _model):
            raise RuntimeError("database unavailable")

    @contextmanager
    def tracked_tenant_session(_tenant_id):
        try:
            yield BrokenSession()
        except Exception:
            lifecycle["rollback"] = True
            raise
        finally:
            lifecycle["close"] = True

    monkeypatch.setattr(
        coding_test_ai_service, "tenant_session", tracked_tenant_session
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        coding_test_ai_service.generate_coding_evaluation_background(
            uuid4(), uuid4()
        )

    assert lifecycle == {"rollback": True, "close": True}
