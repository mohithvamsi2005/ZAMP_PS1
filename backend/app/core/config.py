from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "sqlite:///./data/app.db"

    # LLM Provider — supports "openrouter" or "llamacpp"
    llm_provider: str = "openrouter"
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    llm_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"

    # LLM runtime
    llm_timeout_seconds: int = 120
    llm_max_retries: int = 1

    # Upload
    upload_dir: str = "./data/uploads"
    max_upload_mb: int = 20

    # Bootstrap / CORS
    auto_seed_on_empty: bool = False
    cors_origins: str = "http://localhost:5173"

    # Access control (Phase-8 hardening) — see app/core/security.py
    # When write_token is set, guarded endpoints require the X-Zamp-Token header.
    # When empty, guarded endpoints only serve loopback clients.
    write_token: str = ""
    diagnostic_rate_per_minute: int = 10
    upload_rate_per_minute: int = 30

    # Single-tenant token auth (Phase 9) — see app/core/auth.py
    # AUTH_PASSWORD unset → auth disabled (local dev / tests). When set:
    # every /api/* route except /api/auth/* requires a session cookie
    # or Authorization: Bearer <AUTH_PASSWORD>.
    auth_password: str = ""
    auth_secret: str = ""          # optional dedicated HMAC secret
    auth_secure_cookie: bool = False  # set true behind HTTPS/TLS

    # Production environment guard
    environment: str = "development"  # "production" | "development"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
