import os
from pathlib import Path

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.auth import is_enabled, session_ok, bearer_ok
from app.api.routes_health import router as health_router
from app.api.routes_extraction import router as extraction_router
from app.api.routes_matching import router as matching_router
from app.api.routes_decision import router as decision_router
from app.api.routes_uploads import router as upload_router
from app.api.routes_runs import router as runs_router
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_auth import router as auth_router

settings = get_settings()
setup_logging()

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

_PUBLIC_API_PATHS = {"/api/auth/login", "/api/auth/status"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.db.session import init_db
    if settings.database_url.startswith("sqlite:///"):
        db_file = settings.database_url.removeprefix("sqlite:///")
        if db_file and db_file != ":memory:":
            Path(db_file).parent.mkdir(parents=True, exist_ok=True)
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    init_db()
    if settings.auto_seed_on_empty:
        from app.db.session import SessionLocal
        from app.db.models import Vendor
        from app.db.seed import seed
        db = SessionLocal()
        try:
            empty = db.query(Vendor.id).first() is None
        finally:
            db.close()
        if empty:
            seed()
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
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(extraction_router)
app.include_router(matching_router)
app.include_router(decision_router)
app.include_router(upload_router)
app.include_router(runs_router)
app.include_router(dashboard_router)
app.include_router(auth_router)


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    """/api/* requires a session cookie or Bearer token when auth is enabled."""
    if not is_enabled():
        return await call_next(request)
    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)  # static assets + index.html: public
    if path in _PUBLIC_API_PATHS:
        return await call_next(request)
    if session_ok(request) or bearer_ok(request):
        return await call_next(request)
    return JSONResponse({"detail": "Authentication required"}, status_code=401)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.auth_secure_cookie:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    # Inline styles are used by the design system — only style-src allows it
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'"
    )
    return response


# ── Frontend (built SPA) ─────────────────────────────────────────────────────


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_catch_all(full_path: str):
    """Serve the built SPA; unknown paths fall back to index.html (client-side routing)."""
    if full_path.startswith("api/"):
        # Unmatched API path — 404, never HTML
        return JSONResponse({"detail": "Not found"}, status_code=404)
    if not FRONTEND_DIST.is_dir():
        return JSONResponse(
            {"detail": "Frontend build not found — run `npm run build` in frontend/ first"},
            status_code=503,
        )

    candidate = (FRONTEND_DIST / full_path).resolve() if full_path else None
    dist_resolved = FRONTEND_DIST.resolve()
    if candidate is not None and candidate.is_file() and (
        candidate == dist_resolved or dist_resolved in candidate.parents
    ):
        return FileResponse(candidate)

    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return JSONResponse({"detail": "index.html missing"}, status_code=503)
