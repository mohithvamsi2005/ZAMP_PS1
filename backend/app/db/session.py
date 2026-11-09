from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30},  # SQLite-only
    echo=False,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):
    """Apply per-connection SQLite pragmas.

    PRAGMAs do not persist across connections, so foreign-key enforcement and a
    busy-timeout are applied on every new connection. This replaces the previous
    per-session helper which ran the PRAGMA on a throwaway pooled connection and
    was therefore unreliable.
    """
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA busy_timeout = 30000")
        finally:
            cursor.close()


def enable_sqlite_foreign_keys(session) -> None:
    """Backwards-compatible helper: ensure FK enforcement for a session.

    FK pragma is now applied at the engine's connect event, so this is retained
    only for compatibility with existing call sites (seed, tests).
    """
    if settings.database_url.startswith("sqlite"):
        session.execute(text("PRAGMA foreign_keys = ON"))


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Safe to call repeatedly. Existing DBs must be migrated
    with `alembic upgrade head` when the schema changes (see migrations/)."""
    from app.db.models import Base
    Base.metadata.create_all(bind=engine)
