"""Single-tenant token auth for the deployed demo instance.

Enabled ONLY when AUTH_PASSWORD is set in the environment (disabled by default
so local dev and the test-suite run unchanged). When enabled:

  * every /api/* route except /api/auth/login and /api/auth/status requires
    either the signed session cookie or Authorization: Bearer <AUTH_PASSWORD>;
  * /api/auth/login sets an HttpOnly, SameSite=Strict cookie whose value is an
    HMAC-SHA256 signature of a constant payload (there is no user store);
  * /health stays public for monitors.

This is deliberately small. It is not SSO, RBAC or multi-user — see
SECURITY_POSTURE.md before deploying beyond a trusted operator.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Request

from app.core.config import get_settings
from app.core.security import _record_hit, reset_rate_limiter  # noqa: F401  (exposed for tests)

SESSION_COOKIE = "zamp_session"

_PAYLOAD = "zamp-phase9-session-v1"


def is_enabled() -> bool:
    return bool(get_settings().auth_password.strip())


def _secret() -> bytes:
    s = get_settings()
    # Prefer a dedicated secret; fall back to the password hash so the two env
    # vars stay orthogonal when both set, without ever storing plaintext.
    seed = s.auth_secret.strip() if s.auth_secret.strip() else s.auth_password
    return hashlib.sha256(seed.encode()).digest()


def make_session_value() -> str:
    payload = f"{_PAYLOAD}:{int(time.time())}"
    return f"{payload}.{_sign(payload)}"


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def verify_session_value(value: str | None) -> bool:
    if not value or "." not in value:
        return False
    payload, sig = value.rsplit(".", 1)
    if not hmac.compare_digest(_sign(payload), sig):
        return False
    if not payload.startswith(_PAYLOAD + ":"):
        return False
    try:
        ts = int(payload.split(":", 1)[1])
    except ValueError:
        return False
    return 0 <= time.time() - ts < 12 * 3600  # 12 h sessions


def bearer_ok(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return False
    supplied = auth.split(" ", 1)[1].strip()
    return hmac.compare_digest(supplied, get_settings().auth_password)


def session_ok(request: Request) -> bool:
    return verify_session_value(request.cookies.get(SESSION_COOKIE))


def login_rate_limit_ok(host: str) -> bool:
    return _record_hit(f"login:{host}", 5)
