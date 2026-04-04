"""Simple in-memory rate limiter middleware for FastAPI.

Uses a sliding-window counter per client IP. Configurable via env vars:
  RATE_LIMIT_PER_MINUTE  — general API limit (default: 120)
  RATE_LIMIT_EVOLUTION   — evolution start limit (default: 10)

No external dependencies required.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


@dataclass
class _BucketEntry:
    timestamps: list[float] = field(default_factory=list)


class RateLimiter:
    """Sliding-window rate limiter keyed by client IP."""

    def __init__(self, requests_per_minute: int = 120):
        self.rpm = requests_per_minute
        self.window = 60.0  # seconds
        self._buckets: dict[str, _BucketEntry] = defaultdict(_BucketEntry)

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """Check if request is allowed. Returns (allowed, remaining)."""
        now = time.monotonic()
        entry = self._buckets[key]

        # Prune old timestamps outside the window
        cutoff = now - self.window
        entry.timestamps = [t for t in entry.timestamps if t > cutoff]

        remaining = max(0, self.rpm - len(entry.timestamps))
        if len(entry.timestamps) >= self.rpm:
            return False, 0

        entry.timestamps.append(now)
        return True, remaining - 1

    def cleanup(self) -> None:
        """Remove stale entries (call periodically to prevent memory growth)."""
        now = time.monotonic()
        cutoff = now - self.window * 2
        stale = [k for k, v in self._buckets.items() if not v.timestamps or v.timestamps[-1] < cutoff]
        for k in stale:
            del self._buckets[k]


# Singleton limiters (lazily initialized, reset via reset_limiters())
_general_limiter: RateLimiter | None = None
_evolution_limiter: RateLimiter | None = None
_cleanup_counter = 0


def _get_limiters() -> tuple[RateLimiter, RateLimiter]:
    global _general_limiter, _evolution_limiter
    if _general_limiter is None:
        general_rpm = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "120"))
        evolution_rpm = int(os.environ.get("RATE_LIMIT_EVOLUTION", "10"))
        _general_limiter = RateLimiter(general_rpm)
        _evolution_limiter = RateLimiter(evolution_rpm)
    return _general_limiter, _evolution_limiter


def reset_limiters() -> None:
    """Reset singleton limiters so they re-read env vars. Used in tests."""
    global _general_limiter, _evolution_limiter
    _general_limiter = None
    _evolution_limiter = None


def _client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For behind reverse proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that enforces per-IP rate limits.

    - General limit applies to all /api/ endpoints
    - Stricter limit applies to POST /api/evolution/start
    - Health and WebSocket endpoints are excluded
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        method = request.method

        # Skip non-API paths (health, ws, static assets)
        if not path.startswith("/api/"):
            return await call_next(request)

        general, evolution = _get_limiters()

        # Allow disabling rate limiting (e.g. in tests) via RATE_LIMIT_PER_MINUTE=0
        if general.rpm <= 0:
            return await call_next(request)

        ip = _client_ip(request)

        # Periodic cleanup (every 500 requests)
        global _cleanup_counter
        _cleanup_counter += 1
        if _cleanup_counter >= 500:
            _cleanup_counter = 0
            general.cleanup()
            evolution.cleanup()
            # Also purge stale EventBus buffers
            event_bus = getattr(request.app.state, "event_bus", None)
            if event_bus is not None:
                event_bus.purge_stale()

        # Stricter limit for evolution start (expensive LLM calls)
        if method == "POST" and path.rstrip("/") == "/api/evolution/start":
            allowed, remaining = evolution.is_allowed(ip)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded for evolution runs. Try again later."},
                    headers={"Retry-After": "60"},
                )

        # General rate limit
        allowed, remaining = general.is_allowed(ip)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": "60"},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
