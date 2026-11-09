from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "sqlite:///./data/app.db"

    # LLM Provider — supports "openrouter" or "llamacpp"
    llm_provider: str = "openrouter"
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    llm_model: str = "meta-llama/llama-3.2-3b-instruct:free"

    # LLM runtime
    llm_timeout_seconds: int = 120
    llm_max_retries: int = 1

    # Upload
    upload_dir: str = "./data/uploads"
    max_upload_mb: int = 20

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
