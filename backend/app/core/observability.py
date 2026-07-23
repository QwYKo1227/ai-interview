"""Request and background logging context with conservative secret redaction."""

from contextlib import contextmanager
from contextvars import ContextVar
import logging
import re
from typing import Iterator
from uuid import uuid4

from fastapi import FastAPI, Request


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_BEARER_PATTERN = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+")
_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|smtp[_-]?password|password|secret|token)\b"
    r"\s*[:=]\s*([^\s,;]+)"
)

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_tenant_id: ContextVar[str | None] = ContextVar("tenant_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)
_task_id: ContextVar[str | None] = ContextVar("task_id", default=None)
_resource_id: ContextVar[str | None] = ContextVar("resource_id", default=None)

request_logger = logging.getLogger("app.request")


def redact_sensitive(value: object) -> str:
    rendered = str(value)
    rendered = _BEARER_PATTERN.sub(r"\1[REDACTED]", rendered)
    return _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", rendered)


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_sensitive(record.getMessage())
        record.args = ()
        defaults = {
            "request_id": _request_id.get(),
            "tenant_id": _tenant_id.get(),
            "user_id": _user_id.get(),
            "task_id": _task_id.get(),
            "resource_id": _resource_id.get(),
        }
        for name, value in defaults.items():
            if not hasattr(record, name):
                setattr(record, name, value)
        return True


def configure_logging_redaction() -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(item, SensitiveDataFilter) for item in handler.filters):
            handler.addFilter(SensitiveDataFilter())


def current_request_id() -> str | None:
    return _request_id.get()


@contextmanager
def logging_context(
    *,
    request_id: str | None = None,
    tenant_id: object | None = None,
    user_id: object | None = None,
    task_id: object | None = None,
    resource_id: object | None = None,
) -> Iterator[None]:
    values = (
        (_request_id, request_id),
        (_tenant_id, None if tenant_id is None else str(tenant_id)),
        (_user_id, None if user_id is None else str(user_id)),
        (_task_id, None if task_id is None else str(task_id)),
        (_resource_id, None if resource_id is None else str(resource_id)),
    )
    tokens = [(context, context.set(value)) for context, value in values]
    try:
        yield
    finally:
        for context, token in reversed(tokens):
            context.reset(token)


def _safe_request_id(request: Request) -> str:
    candidate = request.headers.get("x-request-id", "").strip()
    if candidate and REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid4().hex


def _signed_identity(request: Request) -> tuple[str | None, str | None]:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None, None
    try:
        from app.core.security import decode_access_token

        claims = decode_access_token(token)
    except Exception:
        return None, None
    return str(claims.tenant_id), str(claims.user_id)


def install_observability(app: FastAPI) -> None:
    if getattr(app.state, "observability_installed", False):
        return
    app.state.observability_installed = True
    configure_logging_redaction()

    @app.middleware("http")
    async def request_observability(request: Request, call_next):
        request_id = _safe_request_id(request)
        tenant_id, user_id = _signed_identity(request)
        status_code = 500
        with logging_context(
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=user_id,
        ):
            try:
                response = await call_next(request)
                status_code = response.status_code
                response.headers["X-Request-ID"] = request_id
                return response
            finally:
                matched_route = request.scope.get("route")
                route_template = getattr(matched_route, "path", "<unmatched>")
                request_logger.info(
                    "request.completed",
                    extra={
                        "request_id": request_id,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "route": route_template,
                        "status": status_code,
                    },
                )
