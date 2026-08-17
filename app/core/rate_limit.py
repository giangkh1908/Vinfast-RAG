"""Rate limiter + backpressure middleware.

Token-bucket rate limiter per IP (in-memory, no Redis dependency).
Backpressure semaphore to limit concurrent in-flight requests.

Design decisions:
- In-memory: works without Redis, sufficient for single-instance deployment.
- Per-IP: fair share across users, prevents single user from monopolizing.
- Token bucket: allows bursts (e.g., 3 requests burst) while enforcing average RPM.
- Backpressure: hard limit on concurrent requests to prevent overload.
  Returns 503 Service Unavailable when limit reached.
"""
import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings

logger = logging.getLogger("bds.ratelimit")


@dataclass
class _TokenBucket:
    """Token bucket for rate limiting."""
    tokens: float
    last_refill: float
    capacity: float
    refill_rate: float  # tokens per second

    def consume(self, now: float = None) -> bool:
        """Try to consume 1 token. Returns True if allowed."""
        if now is None:
            now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    def retry_after(self) -> float:
        """Seconds until next token available."""
        if self.tokens >= 1.0:
            return 0.0
        return (1.0 - self.tokens) / self.refill_rate


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP token bucket rate limiter.

    Config via env:
    - RATE_LIMIT_RPM: requests per minute per IP (default: 30)
    - RATE_LIMIT_BURST: burst capacity (default: 5)
    """

    def __init__(self, app, rpm: int = 30, burst: int = 5):
        super().__init__(app)
        self.rpm = rpm
        self.burst = burst
        self.refill_rate = rpm / 60.0  # tokens per second
        self._buckets: dict[str, _TokenBucket] = defaultdict(
            lambda: _TokenBucket(
                tokens=float(burst),
                last_refill=time.monotonic(),
                capacity=float(burst),
                refill_rate=self.refill_rate,
            )
        )
        self._cleanup_interval = 300  # cleanup every 5 min
        self._last_cleanup = time.monotonic()

    def _cleanup_stale(self):
        """Remove old buckets to prevent memory leak."""
        now = time.monotonic()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        stale_keys = [
            ip for ip, bucket in self._buckets.items()
            if now - bucket.last_refill > 600  # 10 min idle
        ]
        for ip in stale_keys:
            del self._buckets[ip]
        if stale_keys:
            logger.info("Cleaned up %d stale rate limit buckets", len(stale_keys))

    async def dispatch(self, request: Request, call_next):
        if not settings.rate_limit_enabled:
            return await call_next(request)

        # Skip rate limiting for static files and health checks
        path = request.url.path
        if path.startswith("/static") or path == "/api/health":
            return await call_next(request)

        # Extract client IP (respect X-Forwarded-For behind proxy)
        client_ip = request.client.host if request.client else "unknown"
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()

        self._cleanup_stale()

        bucket = self._buckets[client_ip]
        now = time.monotonic()

        if not bucket.consume(now):
            retry = bucket.retry_after()
            logger.warning(
                "Rate limit exceeded: ip=%s path=%s retry_after=%.1fs",
                client_ip, path, retry,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too many requests",
                    "retry_after": round(retry, 1),
                },
                headers={"Retry-After": str(int(retry) + 1)},
            )

        return await call_next(request)


class BackpressureMiddleware(BaseHTTPMiddleware):
    """Hard limit on concurrent in-flight requests.

    When limit reached, returns 503 to new requests immediately.
    Prevents server overload from too many simultaneous LLM calls.

    Config via env:
    - BACKPRESSURE_MAX: max concurrent requests (default: 50)
    """

    def __init__(self, app, max_concurrent: int = 50):
        super().__init__(app)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max = max_concurrent
        self._inflight = 0

    async def dispatch(self, request: Request, call_next):
        # Skip for static files
        if request.url.path.startswith("/static"):
            return await call_next(request)

        if self._semaphore.locked():
            logger.warning(
                "Backpressure: %d/%d in-flight requests, rejecting new one",
                self._inflight, self._max,
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": "Service temporarily unavailable",
                    "message": "Too many concurrent requests. Please retry.",
                    "in_flight": self._inflight,
                    "max": self._max,
                },
                headers={"Retry-After": "5"},
            )

        async with self._semaphore:
            self._inflight += 1
            try:
                return await call_next(request)
            finally:
                self._inflight -= 1

    def stats(self) -> dict:
        return {
            "max": self._max,
            "in_flight": self._inflight,
        }


def setup_rate_limiting(app: FastAPI):
    """Attach rate limiter + backpressure to FastAPI app."""
    rpm = int(settings.rate_limit_rpm) if hasattr(settings, "rate_limit_rpm") else 30
    burst = int(settings.rate_limit_burst) if hasattr(settings, "rate_limit_burst") else 5
    max_concurrent = int(settings.backpressure_max) if hasattr(settings, "backpressure_max") else 50

    app.add_middleware(BackpressureMiddleware, max_concurrent=max_concurrent)
    app.add_middleware(RateLimitMiddleware, rpm=rpm, burst=burst)

    logger.info(
        "Rate limiting: %d RPM per IP (burst=%d), backpressure: %d max concurrent",
        rpm, burst, max_concurrent,
    )
