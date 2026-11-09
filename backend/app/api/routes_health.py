from fastapi import APIRouter
from sqlalchemy import text
from app.db.session import engine
from app.schemas.health import HealthResponse, PingResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
def health_check() -> dict:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    return HealthResponse(
        status="ok" if db_status == "connected" else "degraded",
        service="zamp-invoice-intelligence",
        database=db_status,
    )


@router.get("/ping", response_model=PingResponse)
def ping() -> PingResponse:
    return PingResponse(pong=True)
