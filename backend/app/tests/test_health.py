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
