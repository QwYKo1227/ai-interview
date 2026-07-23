"""Small in-process tiered limiter for abuse-prone public endpoints."""

from collections import OrderedDict, deque
from dataclasses import dataclass
import hashlib
import os
import threading
import time

from fastapi import HTTPException, Request, status

from app.core.proxy import resolve_client_ip


@dataclass(frozen=True)
class RateLimit:
    limit: int
    window_seconds: int

    def __post_init__(self):
        if self.limit < 1 or self.window_seconds < 1:
            raise ValueError("rate limit values must be positive")


def _default_policies():
    return {
        "login": RateLimit(
            limit=int(os.getenv("RATE_LIMIT_LOGIN", "10")), window_seconds=60
        ),
        "public_upload": RateLimit(
            limit=int(os.getenv("RATE_LIMIT_PUBLIC_UPLOAD", "10")), window_seconds=60
        ),
        "public_code_run": RateLimit(
            limit=int(os.getenv("RATE_LIMIT_PUBLIC_CODE_RUN", "30")), window_seconds=60
        ),
        "public_code_submit": RateLimit(
            limit=int(os.getenv("RATE_LIMIT_PUBLIC_CODE_SUBMIT", "10")), window_seconds=60
        ),
        "public_essay_submit": RateLimit(
            limit=int(os.getenv("RATE_LIMIT_PUBLIC_ESSAY_SUBMIT", "5")), window_seconds=60
        ),
    }


class ApplicationRateLimiter:
    def __init__(
        self,
        *,
        policies=None,
        clock=time.monotonic,
        max_buckets: int | None = None,
    ):
        self.policies = dict(_default_policies() if policies is None else policies)
        self.clock = clock
        self.max_buckets = (
            int(os.getenv("RATE_LIMIT_MAX_BUCKETS", "10000"))
            if max_buckets is None
            else max_buckets
        )
        if self.max_buckets < 1:
            raise ValueError("max_buckets must be positive")
        self._events = OrderedDict()
        self._lock = threading.Lock()

    def check(self, bucket: str, identity: str) -> int | None:
        return self.check_many(bucket, (identity,))

    def check_many(self, bucket: str, identities: tuple[str, ...]) -> int | None:
        policy = self.policies.get(bucket)
        if policy is None:
            return None
        now = self.clock()
        keys = tuple(
            (bucket, hashlib.sha256(identity.encode("utf-8")).hexdigest())
            for identity in dict.fromkeys(identities)
        )
        with self._lock:
            self._prune_expired(now)
            cutoff = now - policy.window_seconds
            retry_after = 0
            for key in keys:
                events = self._events.get(key, ())
                if len(events) >= policy.limit:
                    retry_after = max(
                        retry_after,
                        max(1, int(policy.window_seconds - (now - events[0])) + 1),
                    )
            if retry_after:
                return retry_after
            for key in keys:
                events = self._events.setdefault(key, deque())
                while events and events[0] <= cutoff:
                    events.popleft()
                events.append(now)
                self._events.move_to_end(key)
            while len(self._events) > self.max_buckets:
                self._events.popitem(last=False)
        return None

    def _prune_expired(self, now: float) -> None:
        expired = []
        for key, events in self._events.items():
            policy = self.policies.get(key[0])
            if policy is None:
                expired.append(key)
                continue
            cutoff = now - policy.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                expired.append(key)
        for key in expired:
            self._events.pop(key, None)

    def snapshot(self):
        with self._lock:
            self._prune_expired(self.clock())
            return {key: len(events) for key, events in self._events.items()}


_INITIALIZATION_LOCK = threading.Lock()


def get_rate_limiter(app) -> ApplicationRateLimiter:
    limiter = getattr(app.state, "rate_limiter", None)
    if limiter is not None:
        return limiter
    with _INITIALIZATION_LOCK:
        limiter = getattr(app.state, "rate_limiter", None)
        if limiter is None:
            limiter = ApplicationRateLimiter()
            app.state.rate_limiter = limiter
        return limiter


def enforce_rate_limit(request: Request, bucket: str, *identity_parts: object) -> None:
    client_host = resolve_client_ip(request)
    identities = [f"ip:{client_host}"]
    if identity_parts:
        identities.append(
            "subject:" + "|".join(str(part) for part in identity_parts)
        )
    retry_after = get_rate_limiter(request.app).check_many(bucket, tuple(identities))
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers={"Retry-After": str(retry_after)},
        )
