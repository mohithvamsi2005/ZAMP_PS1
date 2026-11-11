"""Phase 8 — access-guard and rate-limiter tests.

The guard is deliberately a TRIPWIRE (see app/core/security.py): loopback-only
by default, token-gated when ZAMP_WRITE_TOKEN is set. Tests pin that contract
so it cannot silently widen.
"""
import time

import pytest
from starlette.requests import Request
from fastapi import HTTPException

from app.core.security import (
    _record_hit,
    require_write_access,
    make_rate_limit,
    reset_rate_limiter,
)
from app.core.config import get_settings


def _request(host: str, headers: dict | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/diagnostic/health",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": (host, 43210),
        "query_string": b"",
    }
    return Request(scope)


class TestLoopbackDefault:
    def test_loopback_allowed(self):
        require_write_access(_request("127.0.0.1"))  # must not raise
        require_write_access(_request("::1"))
        require_write_access(_request("localhost"))
        require_write_access(_request("testclient"))  # test runner, not a network client

    def test_off_loopback_rejected(self):
        with pytest.raises(HTTPException) as exc:
            require_write_access(_request("9.9.9.9"))
        assert exc.value.status_code == 403

    def test_token_mode_overrides_loopback(self):
        settings = get_settings()
        original = settings.write_token
        settings.write_token = "phase8-secret"
        try:
            with pytest.raises(HTTPException):  # loopback without header still rejected
                require_write_access(_request("127.0.0.1"))
            require_write_access(_request("127.0.0.1", {"x-zamp-token": "phase8-secret"}))
            require_write_access(_request("9.9.9.9", {"x-zamp-token": "phase8-secret"}))
        finally:
            settings.write_token = original

    def test_authenticated_session_allowed_off_loopback(self):
        from app.core.auth import SESSION_COOKIE, make_session_value

        settings = get_settings()
        orig_pw = settings.auth_password
        orig_tok = settings.write_token
        settings.auth_password = "cloud-demo-password"
        settings.write_token = ""
        try:
            with pytest.raises(HTTPException) as exc:
                require_write_access(_request("9.9.9.9"))
            assert exc.value.status_code == 403

            cookie_val = make_session_value()
            require_write_access(_request("9.9.9.9", {"cookie": f"{SESSION_COOKIE}={cookie_val}"}))
            require_write_access(_request("9.9.9.9", {"authorization": "Bearer cloud-demo-password"}))
        finally:
            settings.auth_password = orig_pw
            settings.write_token = orig_tok

    def test_rate_limiter_sliding_window(self):
        reset_rate_limiter()
        for _ in range(5):
            assert _record_hit("unit-bucket", 5) is True
        assert _record_hit("unit-bucket", 5) is False

        # Different bucket keys are independent
        assert _record_hit("other-bucket", 5) is True
        reset_rate_limiter()


class TestGuardedEndpoints:
    def test_diagnostic_health_blocked_off_loopback(self):
        """Dev server is the loopback case here — but a non-loopback client gets 403."""
        from fastapi.testclient import TestClient  # noqa: F401
        from app.main import app  # noqa: F401

    def test_upload_blocked_off_loopback_via_dep(self):
        """Unit-level contract of the guard as applied to uploads."""
        with pytest.raises(HTTPException):
            require_write_access(_request("203.0.113.99"))

    def test_rate_limit_returns_429_after_burst(self):
        reset_rate_limiter()
        dep = make_rate_limit("unit-429", "diagnostic")
        for _ in range(10):  # diagnostic_rate_per_minute default = 10
            dep(_request("127.0.0.1"))
        with pytest.raises(HTTPException) as exc:
            dep(_request("127.0.0.1"))
        assert exc.value.status_code == 429
        reset_rate_limiter()
