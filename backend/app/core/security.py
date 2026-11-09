"""Minimal access control for the Zamp invoice demo deployment.

This is a *tripwire*, not authentication — it stops accidental exposure and
crawl-level abuse, not a determined adversary. Two layers, in priority order:

1. If `write_token` is configured in the environment (ZAMP_WRITE_TOKEN), every
   guarded endpoint requires the matching `X-Zamp-Token` header. Use this the
   moment the server is reachable by anyone but its own machine.
2. Otherwise the guarded endpoints only serve loopback clients
   (127.0.0.1 / ::1 / localhost — plus "testclient" so the test suite keeps
   working without credentials on localhost).

Guarded endpoints are the ones that burn LLM quota or mutate state:
  POST /api/invoices/upload      (full pipeline incl. LLM extraction)
  POST /api/runs/{id}/retry      (re-runs extraction for a failed run)
  /api/diagnostic/*              (diagnostic pipeline incl. LLM extraction)

Read-only endpoints stay open by design (GET /api/runs, /api/invoices, /health…).

Additionally, a small in-memory sliding-window rate limiter caps the number of
guarded calls per minute per client to contain quota burn.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.core.config import get_settings

_LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}

# bucket key → deque of monotonic timestamps
_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def _record_hit(key: str, limit_per_minute: int) -> bool:
    now = time.monotonic()
    with _lock:
        dq = _hits[key]
        while dq and now - dq[0] > 60.0:
            dq.popleft()
        if len(dq) >= limit_per_minute:
            return False
        dq.append(now)
        return True


def reset_rate_limiter() -> None:
    """Test hook — clear all buckets."""
    with _lock:
        _hits.clear()


def require_write_access(request: Request) -> None:
    """Authn-by-token (if configured) or loopback-only enforcement."""
    settings = get_settings()
    token = getattr(settings, "write_token", "") or ""
    if token:
        supplied = request.headers.get("x-zamp-token", "")
        if supplied != token:
            raise HTTPException(status_code=403, detail="Missing or invalid X-Zamp-Token")
        return
    host = request.client.host if request.client else ""
    if host not in _LOOPBACK:
        raise HTTPException(status_code=403, detail="This endpoint is only available to local clients")


def make_rate_limit(bucket: str, kind: str):
    """Dependency factory: sliding-window limiter for one bucket kind."""

    def _dep(request: Request) -> None:
        settings = get_settings()
        limit = (
            settings.diagnostic_rate_per_minute if kind == "diagnostic"
            else settings.upload_rate_per_minute
        )
        host = request.client.host if request.client else "unknown"
        if not _record_hit(f"{bucket}:{host}", limit):
            raise HTTPException(status_code=429, detail="Rate limit exceeded — slow down and try again")

    return _dep
