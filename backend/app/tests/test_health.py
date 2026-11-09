from pathlib import Path
from pydantic import BaseModel
from sqlalchemy import text


class DBCheck(BaseModel):
    connected: bool
    message: str


def check_database() -> DBCheck:
    """Verify SQLite database is reachable."""
    try:
        from app.db.session import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return DBCheck(connected=True, message="Database connected")
    except Exception as e:
        return DBCheck(connected=False, message=str(e))


def test_database_is_reachable():
    """Real connectivity check against the (isolated, per-conftest) database."""
    result = check_database()
    assert result.connected is True
    assert result.message == "Database connected"


def test_health_endpoint_exposes_config_without_secrets(client=None):
    """/health must return provider KIND and model name — never the API key."""
    import json
    from fastapi.testclient import TestClient
    from app.main import app

    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"status", "service", "database", "llm_provider", "llm_model"}
    assert "sk-" not in json.dumps(body).lower()  # no key-shaped material anywhere

