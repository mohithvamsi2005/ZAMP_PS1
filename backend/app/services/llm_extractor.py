"""LLM-powered invoice extraction orchestrator."""
import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.core.config import get_settings
from app.schemas.invoice import ExtractionMetadata, InvoiceExtraction
from app.services.extraction_prompt import build_extraction_prompt
from app.services.llm_providers.base import ExtractionError, InvoiceExtractionProvider
from app.services.llm_providers.llama_cpp import LlamaCppProvider
from app.services.llm_providers.openrouter import OpenRouterProvider

logger = logging.getLogger(__name__)


def _build_provider() -> Optional[InvoiceExtractionProvider]:
    """Instantiate the configured LLM provider, or return None if not configured."""
    settings = get_settings()
    provider_name = settings.llm_provider.lower().strip()
    base_url = settings.llm_base_url.strip()
    api_key = settings.llm_api_key.strip()
    model = settings.llm_model.strip()

    if not base_url:
        logger.warning("LLM_BASE_URL is empty — extraction will be skipped")
        return None

    try:
        if provider_name == "llamacpp" or provider_name == "llama_cpp":
            return LlamaCppProvider(
                base_url=base_url, api_key=api_key, model=model,
                timeout_seconds=settings.llm_timeout_seconds,
                max_retries=settings.llm_max_retries,
            )
        elif provider_name == "openrouter":
            return OpenRouterProvider(
                base_url=base_url, api_key=api_key, model=model,
                timeout_seconds=settings.llm_timeout_seconds,
                max_retries=settings.llm_max_retries,
            )
        else:
            logger.warning("Unknown LLM_PROVIDER=%r — supported: openrouter, llamacpp", provider_name)
            return None
    except Exception as exc:
        logger.error("Failed to initialise LLM provider %r: %s", provider_name, exc)
        return None


def _repair_json(text: str) -> Optional[str]:
    """Best-effort repair of common JSON issues from LLM output."""
    # Strip markdown code fences if present
    stripped = text.strip()
    for prefix in ("```json", "```"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):].lstrip()
    if stripped.endswith("```"):
        stripped = stripped[:-3].rstrip()
    # Try to find the first '{' and last '}'
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        stripped = stripped[start : end + 1]
    return stripped


def _parse_decimal(value) -> Optional[Decimal]:
    """Safely parse a value to Decimal."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def extract_invoice_from_text(
    invoice_text: str,
    metadata: ExtractionMetadata,
) -> InvoiceExtraction:
    """Run the LLM extraction pipeline on pre-extracted document text.

    Returns an InvoiceExtraction with validation applied.
    """
    provider = _build_provider()
    if provider is None:
        return InvoiceExtraction(
            extraction_status="FAILED",
            warnings=["No LLM provider configured — returning empty extraction"],
        )

    prompt_msgs = build_extraction_prompt(invoice_text, model_name=provider.model)

    # First attempt
    raw_response: Optional[dict] = None
    last_error: Optional[Exception] = None

    for attempt in range(1 + provider.max_retries):
        try:
            raw_response = provider.extract_invoice(
                system_message=prompt_msgs["system"],
                user_message=prompt_msgs["user"],
            )
            break
        except ExtractionError as exc:
            last_error = exc
            logger.warning("LLM attempt %d/%d failed: %s", attempt + 1, provider.max_retries + 1, exc)
            if attempt < provider.max_retries:
                continue

    if raw_response is None:
        return InvoiceExtraction(
            extraction_status="FAILED",
            warnings=[f"LLM extraction failed after {provider.max_retries + 1} attempts: {last_error}"],
            source_pages=metadata.source_pages,
        )

    # Parse response into schema
    try:
        extraction = InvoiceExtraction(**raw_response)
    except Exception as exc:
        logger.warning("Schema validation failed on raw LLM output: %s — attempting repair", exc)
        # Retry once with repaired JSON
        for attempt in range(provider.max_retries):
            repaired = _repair_json(json.dumps(raw_response, default=str))
            try:
                parsed = json.loads(repaired)
                extraction = InvoiceExtraction(**parsed)
                break
            except Exception as repair_exc:
                logger.warning("Repair attempt %d failed: %s", attempt + 1, repair_exc)
                if attempt == provider.max_retries - 1:
                    return InvoiceExtraction(
                        extraction_status="FAILED",
                        warnings=[f"LLM response validation failed: {exc}"],
                        source_pages=metadata.source_pages,
                    )
        else:
            # All repairs exhausted — construct from raw with FAILED status
            return InvoiceExtraction(
                extraction_status="FAILED",
                warnings=[f"Failed to validate LLM output after repair attempts: {exc}"],
                source_pages=metadata.source_pages,
            )

    # Add document-level metadata
    if not extraction.source_pages:
        extraction.source_pages = [p["page"] for p in metadata.pages_processed]

    # Normalise decimal fields from string → Decimal
    for field in ("subtotal", "tax_amount", "discount_amount", "total_amount"):
        val = getattr(extraction, field)
        if isinstance(val, str):
            setattr(extraction, field, _parse_decimal(val))

    for item in extraction.line_items:
        for field in ("quantity", "unit_price", "line_total"):
            val = getattr(item, field)
            if isinstance(val, str):
                setattr(item, field, _parse_decimal(val))

    return extraction


def extract_invoice(
    pdf_path,
    ocr_service=None,
) -> tuple[InvoiceExtraction, ExtractionMetadata]:
    """Full pipeline: PDF text extraction → OCR fallback → LLM extraction.

    Returns (extraction_result, processing_metadata).
    """
    from app.services.pdf_extractor import extract_pdf
    from app.services.ocr_service import ocr_needed_pages

    # Step 1: PDF text extraction
    metadata, full_text = extract_pdf(pdf_path)

    # Step 2: OCR fallback for pages that need it
    if ocr_service is None:
        from app.services.ocr_service import OCRService
        ocr_service = OCRService()

    needed_pages = ocr_needed_pages(pdf_path, metadata.pages_processed)
    if needed_pages:
        logger.info("Running OCR on %d pages", len(needed_pages))
        for page_num_1indexed in needed_pages:
            text, confidence = ocr_service.ocr_page(page_num_1indexed - 1, pdf_path)
            # Replace the OCR-required entry with actual OCR result
            for pm in metadata.pages_processed:
                if pm["page"] == page_num_1indexed:
                    pm["method"] = "OCR"
                    pm["confidence"] = confidence
            if text.strip():
                full_text = full_text.replace(
                    f"--- PAGE {page_num_1indexed} ---\n",
                    f"--- PAGE {page_num_1indexed} (OCR) ---\n{text}\n",
                )

    # Step 3: LLM extraction
    extraction = extract_invoice_from_text(full_text, metadata)
    return extraction, metadata
