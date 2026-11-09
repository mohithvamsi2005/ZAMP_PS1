"""OpenRouter provider — uses OpenAI-compatible chat completions API."""
import json
import logging
from typing import Optional

import httpx

from .base import ExtractionError, InvoiceExtractionProvider, parse_llm_json

logger = logging.getLogger(__name__)


class OpenRouterProvider(InvoiceExtractionProvider):
    """OpenRouter provider using the OpenAI-compatible endpoint."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: int = 120, max_retries: int = 1):
        super().__init__(base_url, api_key, model, timeout_seconds, max_retries)
        self._endpoint = f"{self.base_url}/chat/completions"

    def extract_invoice(self, system_message: str, user_message: str) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
            # OpenRouter-specific headers for tracking and control
            "HTTP-Referer": "https://zamp-invoice-intelligence.local",
            "X-Title": "Zamp Invoice Intelligence",
        }

        last_error: Optional[Exception] = None
        for attempt in range(1 + self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(self._endpoint, json=payload, headers=headers)

                if response.status_code == 429:
                    # Rate limit — only retry once for this case
                    if attempt < self.max_retries:
                        logger.warning("OpenRouter rate-limited (attempt %d/%d)", attempt + 1, self.max_retries + 1)
                        continue
                    raise ExtractionError(
                        f"OpenRouter rate limit exceeded after {self.max_retries + 1} attempts",
                        provider="openrouter",
                    )

                if response.status_code >= 400:
                    body = response.text
                    logger.error("OpenRouter error %d: %s", response.status_code, body[:500])
                    raise ExtractionError(
                        f"OpenRouter API error {response.status_code}: {body[:200]}",
                        provider="openrouter",
                    )

                try:
                    data = response.json()
                except json.JSONDecodeError as exc:
                    raise ExtractionError(
                        f"OpenRouter returned a non-JSON response body: {exc}",
                        provider="openrouter",
                    ) from exc
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if not content:
                    raise ExtractionError(
                        "OpenRouter returned empty content",
                        provider="openrouter",
                    )
                return parse_llm_json(content)

            except ExtractionError as exc:
                # Keep the honest rate-limit message intact — never re-wrap as a parse error
                if "rate limit" in str(exc).lower():
                    raise
                last_error = exc
                logger.warning("OpenRouter extraction error (attempt %d): %s", attempt + 1, exc)
                if attempt < self.max_retries:
                    continue
                raise ExtractionError(
                    f"Failed to parse OpenRouter response after {self.max_retries + 1} attempts: {exc}",
                    provider="openrouter",
                    original_error=exc,
                ) from exc

            except (KeyError, IndexError) as exc:
                last_error = exc
                logger.warning("OpenRouter response shape error (attempt %d): %s", attempt + 1, exc)
                if attempt < self.max_retries:
                    continue
                raise ExtractionError(
                    f"Failed to parse OpenRouter response after {self.max_retries + 1} attempts: {exc}",
                    provider="openrouter",
                    original_error=exc,
                ) from exc

            except (httpx.TimeoutException, httpx.HTTPError) as exc:
                last_error = exc
                logger.warning("OpenRouter timeout (attempt %d)", attempt + 1)
                if attempt < self.max_retries:
                    continue
                raise ExtractionError(
                    f"OpenRouter request timed out after {self.timeout_seconds}s",
                    provider="openrouter",
                    original_error=exc,
                ) from exc

        raise ExtractionError(
            "Unexpected exhaustion of retry attempts",
            provider="openrouter",
            original_error=last_error,
        )
