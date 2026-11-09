"""Auth endpoints — always present, always safe to call.

GET  /api/auth/status  → {"required": bool, "authenticated": bool}  (never underestimates)
POST /api/auth/login   → sets HttpOnly, SameSite=Strict session cookie
POST /api/auth/logout  → clears it
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.core.auth import (
    SESSION_COOKIE,
    bearer_ok,
    is_enabled,
    login_rate_limit_ok,
    make_session_value,
    session_ok,
)
from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


@router.get("/status")
async def auth_status(request: Request):
    if not is_enabled():
        return {"required": False, "authenticated": True}
    authed = session_ok(request) or bearer_ok(request)
    return {"required": True, "authenticated": authed}


@router.post("/login")
async def login(req: LoginRequest, request: Request, response: Response):
    host = request.client.host if request.client else "unknown"
    if not login_rate_limit_ok(host):
        raise HTTPException(status_code=429, detail="Too many attempts — try again shortly")

    settings = get_settings()
    if not is_enabled():
        # Auth disabled — say so, don't set any cookie
        return {"required": False, "authenticated": True}

    import hmac as _hmac
    supplied = req.password.encode()
    if _hmac.compare_digest(supplied, settings.auth_password.encode()):
        response.set_cookie(
            SESSION_COOKIE,
            make_session_value(),
            httponly=True,
            samesite="strict",
            secure=bool(getattr(settings, "auth_secure_cookie", False)),
            path="/",
            max_age=12 * 3600,
        )
        logger.info("auth login success from %s", host)
        return {"required": True, "authenticated": True}
    logger.warning("auth login FAILED from %s", host)
    raise HTTPException(status_code=401, detail="Incorrect password")


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"authenticated": False}
