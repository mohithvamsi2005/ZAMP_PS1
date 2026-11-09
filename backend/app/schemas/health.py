from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    database: str
    # Non-secret runtime config only (provider KIND + model alias). The API
    # key is NEVER included — see routes_health.
    llm_provider: str = ""
    llm_model: str = ""


class PingResponse(BaseModel):
    pong: bool
