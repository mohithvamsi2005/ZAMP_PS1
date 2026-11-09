from fastapi import APIRouter
from sqlalchemy import text
from app.db.session import engine
from app.schemas.health import HealthResponse, PingResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
def health_check() -> dict:
    from app.core.config import get_settings
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    settings = get_settings()
    return HealthResponse(
        status="ok" if db_status == "connected" else "degraded",
        service="zamp-invoice-intelligence",
        database=db_status,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
    )


@router.get("/ping", response_model=PingResponse)
def ping() -> PingResponse:
    return PingResponse(pong=True)
