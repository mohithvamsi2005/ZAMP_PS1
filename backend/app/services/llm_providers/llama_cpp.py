"""llama.cpp provider — uses OpenAI-compatible chat completions API."""
import json
import logging
from typing import Optional

import httpx

from .base import ExtractionError, InvoiceExtractionProvider, parse_llm_json

logger = logging.getLogger(__name__)


class LlamaCppProvider(InvoiceExtractionProvider):
    """Remote or local llama.cpp server using the OpenAI-compatible endpoint."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: int = 120, max_retries: int = 1):
        super().__init__(base_url, api_key, model, timeout_seconds, max_retries)
        self._endpoint = f"{self.base_url}/v1/chat/completions"

    def extract_invoice(self, system_message: str, user_message: str) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
        }

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Optional[Exception] = None
        for attempt in range(1 + self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(self._endpoint, json=payload, headers=headers)

                if response.status_code >= 400:
                    body = response.text
                    logger.error("llama.cpp error %d: %s", response.status_code, body[:500])
                    raise ExtractionError(
                        f"llama.cpp API error {response.status_code}: {body[:200]}",
                        provider="llama_cpp",
                    )

                try:
                    data = response.json()
                except json.JSONDecodeError as exc:
                    raise ExtractionError(
                        f"llama.cpp returned a non-JSON response body: {exc}",
                        provider="llama_cpp",
                    ) from exc
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if not content:
                    raise ExtractionError(
                        "llama.cpp returned empty content",
                        provider="llama_cpp",
                    )
                return parse_llm_json(content)

            except ExtractionError as exc:
                last_error = exc
                logger.warning("llama.cpp extraction error (attempt %d): %s", attempt + 1, exc)
                if attempt < self.max_retries:
                    continue
                raise ExtractionError(
                    f"Failed to parse llama.cpp response after {self.max_retries + 1} attempts: {exc}",
                    provider="llama_cpp",
                    original_error=exc,
                ) from exc

            except (KeyError, IndexError) as exc:
                last_error = exc
                logger.warning("llama.cpp response shape error (attempt %d): %s", attempt + 1, exc)
                if attempt < self.max_retries:
                    continue
                raise ExtractionError(
                    f"Failed to parse llama.cpp response after {self.max_retries + 1} attempts: {exc}",
                    provider="llama_cpp",
                    original_error=exc,
                ) from exc

            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_error = exc
                logger.warning("llama.cpp connection error (attempt %d): %s", attempt + 1, exc)
                if attempt < self.max_retries:
                    continue
                raise ExtractionError(
                    f"llama.cpp connection failed after {self.max_retries + 1} attempts",
                    provider="llama_cpp",
                    original_error=exc,
                ) from exc

        raise ExtractionError(
            "Unexpected exhaustion of retry attempts",
            provider="llama_cpp",
            original_error=last_error,
        )
