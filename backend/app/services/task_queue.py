import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Callable, Any, Dict
from uuid import UUID
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
import time
import logging
from app.core.observability import current_request_id, logging_context


logger = logging.getLogger(__name__)


def _tenant_is_active(tenant_id: UUID) -> bool:
    """Read current tenant state immediately before queued execution."""

    from app.config.database import SessionLocal
    from app.models.tenant_models import Tenant, TenantStatus

    db = SessionLocal()
    try:
        return (
            db.query(Tenant.id)
            .filter(Tenant.id == tenant_id, Tenant.status == TenantStatus.ACTIVE)
            .first()
            is not None
        )
    except Exception:
        return False
    finally:
        db.close()


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class QueueTask:
    tenant_id: UUID
    resource_id: UUID | str
    id: str
    task_type: str
    payload: Dict[str, Any]
    callback: Callable
    on_failure: Optional[Callable] = None
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    request_id: Optional[str] = field(default_factory=current_request_id)


class TaskQueue:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        max_concurrent: int = 3,
        retry_delay: float = 5.0,
    ):
        if self._initialized:
            return

        self.max_concurrent = max_concurrent
        self.retry_delay = retry_delay
        self.queue: deque = deque()
        self.queue_lock = threading.Lock()
        self.running_tasks: Dict[str, QueueTask] = {}
        self.running_lock = threading.Lock()
        self.completed_tasks: Dict[str, QueueTask] = {}
        self.completed_lock = threading.Lock()
        self.semaphore = threading.Semaphore(max_concurrent)
        self.executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self.is_running = False
        self.worker_thread: Optional[threading.Thread] = None
        self._initialized = True
        self.tenant_is_active = _tenant_is_active
        self._stats = {
            "total_submitted": 0,
            "total_completed": 0,
            "total_failed": 0,
        }
        self._tenant_stats: Dict[UUID, Dict[str, int]] = {}

    def _stats_for(self, tenant_id: UUID) -> Dict[str, int]:
        if not hasattr(self, "_tenant_stats"):
            self._tenant_stats = {}
        return self._tenant_stats.setdefault(
            tenant_id,
            {"total_submitted": 0, "total_completed": 0, "total_failed": 0},
        )

    def start(self):
        if self.is_running:
            return

        self.is_running = True
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        print(f"[TaskQueue] Started with max_concurrent={self.max_concurrent}")

    def stop(self):
        self.is_running = False
        if self.executor:
            self.executor.shutdown(wait=False)
        print("[TaskQueue] Stopped")

    def submit(
        self,
        tenant_id: UUID,
        resource_id: UUID | str,
        task_id: str,
        task_type: str,
        payload: Dict[str, Any],
        callback: Callable,
        on_failure: Optional[Callable] = None,
    ) -> QueueTask:
        task = QueueTask(
            tenant_id=tenant_id,
            resource_id=resource_id,
            id=task_id,
            task_type=task_type,
            payload=payload,
            callback=callback,
            on_failure=on_failure,
        )

        with self.queue_lock:
            self.queue.append(task)
            self._stats["total_submitted"] += 1
            self._stats_for(tenant_id)["total_submitted"] += 1
            queue_size = len(self.queue)

        with self.running_lock:
            running_size = len(self.running_tasks)

        print(f"[TaskQueue] Task {task_id} submitted. Queue: {queue_size}, Running: {running_size}")

        if not self.is_running:
            self.start()

        return task

    def get_status(self, task_id: str, tenant_id: UUID) -> Optional[Dict[str, Any]]:
        key = (tenant_id, task_id)
        with self.running_lock:
            if key in self.running_tasks:
                task = self.running_tasks[key]
                return {
                    "status": task.status.value,
                    "created_at": task.created_at.isoformat(),
                    "started_at": task.started_at.isoformat() if task.started_at else None,
                }

        with self.completed_lock:
            if key in self.completed_tasks:
                task = self.completed_tasks[key]
                return {
                    "status": task.status.value,
                    "created_at": task.created_at.isoformat(),
                    "started_at": task.started_at.isoformat() if task.started_at else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                    "error": task.error,
                }

        with self.queue_lock:
            for i, task in enumerate(self.queue):
                if task.id == task_id and task.tenant_id == tenant_id:
                    return {
                        "status": task.status.value,
                        "created_at": task.created_at.isoformat(),
                        "queue_position": 1 + sum(
                            1
                            for earlier in list(self.queue)[:i]
                            if earlier.tenant_id == tenant_id
                        ),
                    }

        return None

    def get_stats(self, tenant_id: UUID) -> Dict[str, Any]:
        with self.queue_lock:
            queue_size = sum(1 for task in self.queue if task.tenant_id == tenant_id)
        with self.running_lock:
            running_size = sum(
                1 for task in self.running_tasks.values() if task.tenant_id == tenant_id
            )
        with self.completed_lock:
            completed_size = sum(
                1 for task in self.completed_tasks.values() if task.tenant_id == tenant_id
            )

        return {
            "queue_size": queue_size,
            "running_tasks": running_size,
            "completed_tasks": completed_size,
            "max_concurrent": self.max_concurrent,
            **self._stats_for(tenant_id),
        }

    def get_queue_position(self, task_id: str, tenant_id: UUID) -> Optional[int]:
        with self.queue_lock:
            position = 0
            for task in self.queue:
                if task.tenant_id != tenant_id:
                    continue
                position += 1
                if task.id == task_id:
                    return position
        return None

    def _worker(self):
        while self.is_running:
            try:
                task = None
                with self.queue_lock:
                    if self.queue:
                        task = self.queue.popleft()

                if task:
                    self.executor.submit(self._execute_task, task)
                else:
                    time.sleep(0.5)

            except Exception:
                print("[TaskQueue] Worker error")
                time.sleep(1)

    def _execute_task(self, task: QueueTask):
        with logging_context(
            request_id=task.request_id,
            tenant_id=task.tenant_id,
            task_id=task.id,
            resource_id=task.resource_id,
        ):
            return self._execute_task_in_context(task)

    def _execute_task_in_context(self, task: QueueTask):
        acquired = self.semaphore.acquire(blocking=True)
        if not acquired:
            with self.queue_lock:
                self.queue.appendleft(task)
            return

        try:
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now()

            with self.running_lock:
                self.running_tasks[(task.tenant_id, task.id)] = task

            if not self.tenant_is_active(task.tenant_id):
                task.status = TaskStatus.FAILED
                task.error = "TenantInactive"
                task.completed_at = datetime.now()
                self._stats["total_failed"] += 1
                self._stats_for(task.tenant_id)["total_failed"] += 1
                logger.warning(
                    "Background task rejected for inactive tenant",
                    extra={
                        "tenant_id": str(task.tenant_id),
                        "task_id": task.id,
                        "resource_id": str(task.resource_id),
                    },
                )
                return

            logger.info(
                "Background task started",
                extra={
                    "tenant_id": str(task.tenant_id),
                    "task_id": task.id,
                    "resource_id": str(task.resource_id),
                },
            )

            result = task.callback(
                task.tenant_id, task.resource_id, task.payload
            )

            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            self._stats["total_completed"] += 1
            self._stats_for(task.tenant_id)["total_completed"] += 1

        except Exception as e:
            task.retry_count += 1
            task.error = type(e).__name__

            if task.retry_count < task.max_retries:
                print(f"[TaskQueue] Task {task.id} failed, retrying ({task.retry_count}/{task.max_retries})")
                task.status = TaskStatus.PENDING
                time.sleep(self.retry_delay * task.retry_count)
                with self.queue_lock:
                    self.queue.appendleft(task)
            else:
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.now()
                self._stats["total_failed"] += 1
                self._stats_for(task.tenant_id)["total_failed"] += 1
                print(f"[TaskQueue] Task {task.id} failed permanently")

                if task.on_failure:
                    try:
                        task.on_failure(
                            task.tenant_id, task.resource_id, task.error
                        )
                    except Exception:
                        print("[TaskQueue] Failure callback error")

        finally:
            self.semaphore.release()

            with self.running_lock:
                self.running_tasks.pop((task.tenant_id, task.id), None)

            if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                with self.completed_lock:
                    self.completed_tasks[(task.tenant_id, task.id)] = task
                    if len(self.completed_tasks) > 100:
                        oldest_key = next(iter(self.completed_tasks))
                        del self.completed_tasks[oldest_key]


task_queue = TaskQueue(max_concurrent=3)


def get_task_queue() -> TaskQueue:
    return task_queue
