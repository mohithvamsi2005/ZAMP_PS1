from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # SQLite-only
    echo=False,
)


def enable_sqlite_foreign_keys(session) -> None:
    """SQLite requires explicit PRAGMA foreign_keys = ON per connection."""
    if "sqlite" in str(settings.database_url):
        with engine.connect() as conn:
            conn.execute(text("PRAGMA foreign_keys = ON"))
        session.execute(text("PRAGMA foreign_keys = ON"))


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Safe to call repeatedly."""
    from app.db.models import Base
    Base.metadata.create_all(bind=engine)
