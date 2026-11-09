"""Phase 9 — token auth gate tests."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import get_settings
from app.core.auth import SESSION_COOKIE, verify_session_value, make_session_value
from app.core.security import reset_rate_limiter


@pytest.fixture(autouse=True)
def isolated_auth_state():
    """Auth starts disabled for every test; restore disabled after."""
    settings = get_settings()
    original = settings.auth_password
    settings.auth_password = ""
    reset_rate_limiter()
    yield
    settings.auth_password = ""  # never leak an enabled state into other modules


class TestAuthDisabled:
    def test_api_accessible_when_password_unset(self):
        client = TestClient(app)
        assert client.get("/api/runs").status_code == 200
        assert client.get("/health").status_code == 200

    def test_status_reports_not_required(self):
        client = TestClient(app)
        body = client.get("/api/auth/status").json()
        assert body == {"required": False, "authenticated": True}

    def test_login_is_a_noop_when_disabled(self):
        client = TestClient(app)
        resp = client.post("/api/auth/login", json={"password": "anything"})
        assert resp.status_code == 200
        assert resp.json()["required"] is False
        # No cookie set
        assert SESSION_COOKIE not in resp.cookies


class TestAuthEnabled:
    @pytest.fixture(autouse=True)
    def enable_auth(self):
        settings = get_settings()
        original = settings.auth_password
        settings.auth_password = "correct-horse"
        yield
        settings.auth_password = original

    def test_api_requires_cookie_or_bearer(self):
        client = TestClient(app)
        assert client.get("/api/runs").status_code == 401
        assert client.get("/api/invoices").status_code == 401
        assert client.get("/api/auth/status").status_code == 200  # public

    def test_health_stays_public(self):
        client = TestClient(app)
        assert client.get("/health").status_code == 200

    def test_login_rejects_wrong_password(self):
        client = TestClient(app)
        resp = client.post("/api/auth/login", json={"password": "nope"})
        assert resp.status_code == 401
        assert SESSION_COOKIE not in resp.cookies

    def test_login_sets_cookie_then_api_works(self):
        client = TestClient(app)
        resp = client.post("/api/auth/login", json={"password": "correct-horse"})
        assert resp.status_code == 200
        assert SESSION_COOKIE in resp.cookies

        ok = client.get("/api/runs")
        assert ok.status_code == 200

    def test_bearer_token_grants_access_without_cookie(self):
        client = TestClient(app)
        ok = client.get("/api/runs", headers={"Authorization": "Bearer correct-horse"})
        assert ok.status_code == 200

    def test_logout_clears_cookie(self):
        client = TestClient(app)
        client.post("/api/auth/login", json={"password": "correct-horse"})
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert client.get("/api/runs").status_code == 401

    def test_login_rate_limited(self):
        client = TestClient(app)
        for _ in range(5):
            client.post("/api/auth/login", json={"password": "wrong"})
        resp = client.post("/api/auth/login", json={"password": "wrong"})
        assert resp.status_code == 429


class TestSessionCrypto:
    def test_session_roundtrip(self):
        settings = get_settings()
        original = settings.auth_password
        settings.auth_password = "correct-horse"
        try:
            value = make_session_value()
            assert verify_session_value(value) is True
            assert verify_session_value(value + "tamper") is False
            assert verify_session_value(None) is False
            assert verify_session_value("") is False
        finally:
            settings.auth_password = original
