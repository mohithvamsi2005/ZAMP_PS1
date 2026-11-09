from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.api.routes_health import router as health_router

settings = get_settings()
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.db.session import engine, Base, init_db
    init_db()
    print(f"Backend started — provider={settings.llm_provider}, db={settings.database_url}")
    yield


app = FastAPI(
    title="Zamp Invoice Intelligence",
    description="AI-powered invoice processing: PDF → extraction → matching → deterministic decision",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
