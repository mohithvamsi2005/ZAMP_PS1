"""Phase 6 test configuration — fully isolated database and upload directory.

Environment variables are set here BEFORE any application module is imported,
so every module-level engine/SessionLocal binding (app.db.session and all
services created at import time) binds to the isolated test database.

Tests NEVER touch backend/data/app.db: a disposable SQLite file is created in
a per-pytest-run temp directory, dropped + recreated for every single test
(autouse fixture) so tests cannot leak state into each other.
"""
import os
import tempfile
from pathlib import Path

import pytest

# ── 1. Environment isolation (must happen before `app.*` imports) ────────────
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="zamp_phase6_tests_"))
TEST_DB_FILE = _TMP_ROOT / "test_app.db"
TEST_UPLOAD_DIR = _TMP_ROOT / "uploads"

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE}"
os.environ["UPLOAD_DIR"] = str(TEST_UPLOAD_DIR)
# The deployment singleton settings may carry AUTH_PASSWORD from the developer's
# local .env; tests must always run with auth disabled unless they enable it explicitly.
os.environ["AUTH_PASSWORD"] = ""
os.environ["ALLOW_PUBLIC_WRITE"] = "false"

# Keep noisy-but-expected warnings out of the output without hiding real issues
os.environ.setdefault("PYTHONWARNINGS", "ignore::DeprecationWarning")

# ── 2. Only now may application modules be imported ──────────────────────────
from app.db.models import Base  # noqa: E402
from app.db.session import engine, init_db  # noqa: E402

ALL_TABLES = sorted(Base.metadata.tables)


@pytest.fixture(autouse=True)
def _fresh_database_per_test():
    """Drop and recreate every table around each test.

    Guarantees that no invoice, run or event produced by one test can be seen
    by another — including the services that open their own SessionLocal
    sessions internally (workflow worker, validators, matchers).
    """
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def test_db_path() -> Path:
    """Absolute path of the isolated SQLite file (used by restart-simulation tests)."""
    return TEST_DB_FILE
