"""Small in-process tiered limiter for abuse-prone public endpoints."""

from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import os
import threading
import time

from fastapi import HTTPException, Request, status


@dataclass(frozen=True)
class RateLimit:
    limit: int
    window_seconds: int

    def __post_init__(self):
        if self.limit < 1 or self.window_seconds < 1:
            raise ValueError("rate limit values must be positive")


DEFAULT_POLICIES = {
    "login": RateLimit(
        limit=int(os.getenv("RATE_LIMIT_LOGIN", "10")), window_seconds=60
    ),
    "public_upload": RateLimit(
        limit=int(os.getenv("RATE_LIMIT_PUBLIC_UPLOAD", "10")), window_seconds=60
    ),
    "public_code_run": RateLimit(
        limit=int(os.getenv("RATE_LIMIT_PUBLIC_CODE_RUN", "30")), window_seconds=60
    ),
}


class ApplicationRateLimiter:
    def __init__(self, *, policies=None, clock=time.monotonic):
        self.policies = dict(DEFAULT_POLICIES if policies is None else policies)
        self.clock = clock
        self._events = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, bucket: str, identity: str) -> int | None:
        policy = self.policies.get(bucket)
        if policy is None:
            return None
        now = self.clock()
        key = (bucket, hashlib.sha256(identity.encode("utf-8")).hexdigest())
        with self._lock:
            events = self._events[key]
            cutoff = now - policy.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= policy.limit:
                return max(1, int(policy.window_seconds - (now - events[0])) + 1)
            events.append(now)
        return None

    def snapshot(self):
        with self._lock:
            return {key: len(events) for key, events in self._events.items()}


def _limiter(request: Request) -> ApplicationRateLimiter:
    limiter = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        limiter = ApplicationRateLimiter()
        request.app.state.rate_limiter = limiter
    return limiter


def enforce_rate_limit(request: Request, bucket: str, *identity_parts: object) -> None:
    client_host = request.client.host if request.client is not None else "unknown"
    identity = "|".join([client_host, *(str(part) for part in identity_parts)])
    retry_after = _limiter(request).check(bucket, identity)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers={"Retry-After": str(retry_after)},
        )
