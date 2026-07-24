"""Canonical request-host policy shared by authenticated and public flows."""

from dataclasses import dataclass
import os

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.proxy import normalize_host, resolve_request_host
from app.models.tenant_models import TenantDomain


UNKNOWN_HOST_DETAIL = "Unknown request host"


@dataclass(frozen=True)
class HostResolution:
    hostname: str
    domain: TenantDomain | None


def _unknown_host() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=UNKNOWN_HOST_DETAIL,
    )


def configured_unified_hosts() -> frozenset[str]:
    configured = os.getenv("UNIFIED_ENTRY_HOSTS")
    if configured is None:
        app_env = os.getenv("APP_ENV", "development").lower()
        configured = (
            "testserver"
            if app_env == "test"
            else "localhost,127.0.0.1,::1,interview-local.careray.com"
            if app_env == "development"
            else ""
        )
    hosts = set()
    for item in configured.split(","):
        if not item.strip():
            continue
        try:
            hosts.add(normalize_host(item))
        except ValueError as exc:
            raise RuntimeError("UNIFIED_ENTRY_HOSTS contains an invalid hostname") from exc
    return frozenset(hosts)


def resolve_host(db: Session, raw_host: str) -> HostResolution:
    try:
        hostname = normalize_host(raw_host)
    except ValueError as exc:
        raise _unknown_host() from exc
    # Unified entry hosts do not require a tenant-domain lookup. Besides being
    # cheaper, returning before touching the Session is important for platform
    # mutation routes: SQLAlchemy's implicit read transaction must not collide
    # with the service's explicit atomic transaction below the dependency layer.
    if hostname in configured_unified_hosts():
        return HostResolution(hostname=hostname, domain=None)
    domain = (
        db.query(TenantDomain)
        .filter(TenantDomain.domain == hostname)
        .first()
    )
    if domain is None:
        raise _unknown_host()
    return HostResolution(hostname=hostname, domain=domain)


def resolve_request_origin(db: Session, request: Request) -> HostResolution:
    try:
        hostname = resolve_request_host(request)
    except ValueError as exc:
        raise _unknown_host() from exc
    if hostname in configured_unified_hosts():
        return HostResolution(hostname=hostname, domain=None)

    # Host validation must not leave an implicit read transaction on the
    # business Session used by a platform write immediately afterwards.
    from app.config.database import SessionLocal

    host_db = SessionLocal()
    try:
        resolution = resolve_host(host_db, hostname)
        if resolution.domain is not None:
            # Detach the fully loaded row before rollback so callers can read
            # tenant_id without reopening the short-lived validation Session.
            host_db.expunge(resolution.domain)
        return resolution
    finally:
        host_db.rollback()
        host_db.close()
