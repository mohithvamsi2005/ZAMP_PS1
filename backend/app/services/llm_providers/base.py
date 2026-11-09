"""Abstract base class for LLM providers."""
from abc import ABC, abstractmethod
from typing import Optional


class ExtractionError(Exception):
    """Raised when LLM extraction fails after retries."""

    def __init__(self, message: str, provider: str = "", original_error: Optional[Exception] = None):
        super().__init__(message)
        self.provider = provider
        self.original_error = original_error


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
