"""Abstract base class for LLM providers."""
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Raised when LLM extraction fails after retries."""

    def __init__(self, message: str, provider: str = "", original_error: Optional[Exception] = None):
        super().__init__(message)
        self.provider = provider
        self.original_error = original_error


_FENCE_OPEN = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n?", re.MULTILINE)
_FENCE_CLOSE = re.compile(r"\n?```\s*$", re.MULTILINE)


def parse_llm_json(content: str) -> dict:
    """Safely parse an LLM response string into a dict.

    Real models wrap JSON in markdown fences, add prose around the object, or
    return it bare. Every provider uses this shared helper so the repair
    discipline is identical across openrouter / llama.cpp:

      1. strip markdown fences (```json … ```)
      2. take the first '{' to the last '}' — the JSON object may not be the
         whole response, and trailing prose/text after it is fine
      3. otherwise raise ExtractionError (the orchestrator decides the rest)

    This never invents data — it only recovers syntactically valid JSON.
    """
    if not isinstance(content, str) or not content.strip():
        raise ExtractionError("Empty response from LLM")

    s = content.strip()
    if "```" in s:  # strip fenced wraps without touching inner content
        s = _FENCE_OPEN.sub("", s, count=1)
        s = _FENCE_CLOSE.sub("", s)

    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ExtractionError(
            f"No JSON object in LLM response (first bytes: {s[:120]!r})"
        )

    candidate = s[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"Invalid JSON in LLM response: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ExtractionError("LLM response JSON is not an object")
    return parsed


class InvoiceExtractionProvider(ABC):
    """Base class for LLM providers that extract structured invoice data."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: int = 120, max_retries: int = 1):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    @abstractmethod
    def extract_invoice(self, system_message: str, user_message: str) -> dict:
        """Call the LLM and return the raw response dict.
        
        Raises ExtractionError on unrecoverable failure.
        """
        ...

    def get_provider_name(self) -> str:
        return self.__class__.__name__
