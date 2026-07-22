import ast
import inspect
import threading
from contextlib import contextmanager
from collections import deque
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from unittest.mock import MagicMock

from app.models.models import CodingSubmission, CodingTest, CodingTestStatus, CodingTestType
from app.services import (
    coding_test_ai_service,
    coding_test_service,
    interview_service,
    resume_service,
)
from app.services.task_queue import QueueTask, TaskQueue, TaskStatus


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

ROUTE_BACKGROUND_FUNCTIONS = []


def _route_background_functions():
    from app.routes import interviews

    return [
        interviews.generate_evaluation_from_transcript,
        interviews.generate_combined_evaluation,
    ]


@pytest.mark.parametrize("task", BACKGROUND_FUNCTIONS, ids=lambda func: func.__name__)
def test_every_background_function_starts_with_tenant_uuid(task):
    parameters = list(inspect.signature(task).parameters.values())
    assert parameters[0].name == "tenant_id"
    assert parameters[0].annotation in (UUID, "UUID")


@pytest.mark.parametrize("task", BACKGROUND_FUNCTIONS[:3], ids=lambda func: func.__name__)
def test_resume_queue_callbacks_start_with_tenant_and_resource(task):
    parameters = list(inspect.signature(task).parameters.values())
    assert [parameter.name for parameter in parameters[:2]] == [
        "tenant_id",
        "resume_id",
    ]


@pytest.mark.parametrize("task", _route_background_functions(), ids=lambda func: func.__name__)
def test_route_background_functions_start_with_tenant_and_resource(task):
    parameters = list(inspect.signature(task).parameters.values())
    assert [parameter.name for parameter in parameters[:2]] == [
        "tenant_id",
        "interview_id",
    ]


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
        test_resume.id,
        {"position_id": test_resume.position_id},
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
    assert submitted["resource_id"] == resume_id


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


@pytest.mark.parametrize("kind", ["code", "essay", "choice"])
def test_public_submission_copies_non_null_tenant_from_resolved_test(
    db, tenant_a, test_user, monkeypatch, kind
):
    coding_test = CodingTest(
        tenant_id=tenant_a.id,
        title="Tenant test",
        test_type=CodingTestType.ALGORITHM,
        public_token=f"token-{kind}",
        status=CodingTestStatus.PUBLISHED,
        created_by=test_user.id,
        questions=[],
        test_cases=[],
    )
    db.add(coding_test)
    db.commit()
    background_tasks = MagicMock()
    monkeypatch.setattr(
        coding_test_service,
        "run_code_against_tests",
        lambda **_kwargs: {"passed": True, "score": 100},
    )

    if kind == "code":
        submission = coding_test_service.submit_public_code(
            db, background_tasks, coding_test.public_token, "A", "a@test.com", "pass", "python"
        )
    elif kind == "essay":
        submission = coding_test_service.submit_essay_answers(
            db, background_tasks, coding_test.public_token, "A", "a@test.com", []
        )
    else:
        submission = coding_test_service.submit_choice_answers(
            db, coding_test.public_token, "A", "a@test.com", []
        )

    assert submission.tenant_id == tenant_a.id
    assert db.get(CodingSubmission, submission.id).tenant_id == tenant_a.id
    if kind in {"code", "essay"}:
        args = background_tasks.add_task.call_args.args
        assert args[:3] == (args[0], submission.tenant_id, submission.id)


def test_resume_parse_exception_rolls_back_and_raises_safe_error(monkeypatch):
    db = MagicMock()
    resume = MagicMock(file_path="resume.pdf")
    db.query.return_value.filter.return_value.first.return_value = resume
    db.commit.side_effect = RuntimeError("Authorization: secret-token")

    with pytest.raises(RuntimeError, match="resume parsing failed") as exc_info:
        resume_service._process_resume_task(
            db, uuid4(), uuid4(), {"position_id": uuid4()}
        )

    db.rollback.assert_called_once()
    assert "secret-token" not in str(exc_info.value)


def test_task_queue_retries_then_marks_failed_with_explicit_resource_arguments():
    tenant_id, resume_id = uuid4(), uuid4()
    callback_calls = []
    failure_calls = []

    def callback(actual_tenant_id, actual_resume_id, payload):
        callback_calls.append((actual_tenant_id, actual_resume_id, payload))
        raise RuntimeError("Authorization: secret-token")

    def on_failure(actual_tenant_id, actual_resume_id, error):
        failure_calls.append((actual_tenant_id, actual_resume_id, error))

    task = QueueTask(
        tenant_id=tenant_id,
        resource_id=resume_id,
        id=str(resume_id),
        task_type="resume_parse",
        payload={"position_id": uuid4()},
        callback=callback,
        on_failure=on_failure,
        max_retries=2,
    )
    queue = object.__new__(TaskQueue)
    queue.semaphore = threading.Semaphore(1)
    queue.retry_delay = 0
    queue.queue = deque()
    queue.queue_lock = threading.Lock()
    queue.running_tasks = {}
    queue.running_lock = threading.Lock()
    queue.completed_tasks = {}
    queue.completed_lock = threading.Lock()
    queue._stats = {"total_completed": 0, "total_failed": 0}

    queue._execute_task(task)
    assert task.status == TaskStatus.PENDING
    queue._execute_task(task)

    assert task.status == TaskStatus.FAILED
    assert callback_calls == [
        (tenant_id, resume_id, task.payload),
        (tenant_id, resume_id, task.payload),
    ]
    assert failure_calls == [(tenant_id, resume_id, "RuntimeError")]
    assert "secret-token" not in task.error


@pytest.mark.parametrize(
    "worker,args",
    [
        (interview_service._generate_questions_background, (uuid4(), [], 5)),
        (interview_service._generate_evaluation_background, (uuid4(), {})),
    ],
)
def test_interview_worker_failure_rolls_back_before_raising(worker, args):
    db = MagicMock()
    db.query.side_effect = RuntimeError("transaction aborted Authorization: secret")

    with pytest.raises(RuntimeError, match="background task failed") as exc_info:
        worker(db, *args)

    db.rollback.assert_called_once()
    assert "secret" not in str(exc_info.value)
