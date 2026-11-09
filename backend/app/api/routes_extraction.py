"""Diagnostic extraction endpoint for Phase 3 testing."""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import hashlib
import logging
import os

from app.core.config import get_settings
from app.core.security import require_write_access, make_rate_limit
from app.services.pdf_extractor import extract_pdf, validate_pdf, sha256_file
from app.services.ocr_service import OCRService
from app.services.llm_extractor import extract_invoice

logger = logging.getLogger(__name__)
# Guarded: burns LLM quota — token-or-loopback access control
router = APIRouter(prefix="/api/diagnostic", tags=["diagnostic"],
                   dependencies=[Depends(require_write_access)])


class ExtractionResult(BaseModel):
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    currency: Optional[str] = None
    po_reference: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_tax_id: Optional[str] = None
    subtotal: Optional[str] = None
    tax_amount: Optional[str] = None
    discount_amount: Optional[str] = None
    total_amount: Optional[str] = None
    line_items_count: int = 0
    extraction_status: str = "SUCCESS"
    warnings: List[str] = []


class PDFMetadata(BaseModel):
    page_count: int
    document_hash: str
    pages_processed: List[dict]
    total_chars_extracted: int
    warnings: List[str]


@router.post("/extract")
async def diagnostic_extract(
    request: Request,
    file: UploadFile = File(...),
    _gate: None = Depends(make_rate_limit("diagnostic", "diagnostic")),
):
    """Upload a PDF and run the full extraction pipeline (no DB write).

    Returns extracted data + processing metadata for inspection.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    settings = get_settings()
    max_bytes = settings.max_upload_mb * 1024 * 1024

    contents = await file.read()
    if len(contents) > max_bytes:
        raise HTTPException(status_code=400, detail=f"File exceeds {settings.max_upload_mb} MB limit")

    # Save to temp location for processing
    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix="extract_diag_")
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(contents)

        pdf_path = __import__("pathlib").Path(tmp_path)

        # Validate
        validation_errors = validate_pdf(pdf_path, max_upload_mb=settings.max_upload_mb)
        if validation_errors:
            raise HTTPException(status_code=400, detail=validation_errors)

        # Extract
        ocr_service = OCRService()
        extraction, metadata = extract_invoice(pdf_path, ocr_service=ocr_service)

        result = ExtractionResult(
            invoice_number=extraction.invoice_number,
            invoice_date=extraction.invoice_date,
            due_date=extraction.due_date,
            currency=extraction.currency,
            po_reference=extraction.po_reference,
            vendor_name=extraction.vendor_name,
            vendor_tax_id=extraction.vendor_tax_id,
            subtotal=str(extraction.subtotal) if extraction.subtotal is not None else None,
            tax_amount=str(extraction.tax_amount) if extraction.tax_amount is not None else None,
            discount_amount=str(extraction.discount_amount) if extraction.discount_amount is not None else None,
            total_amount=str(extraction.total_amount) if extraction.total_amount is not None else None,
            line_items_count=len(extraction.line_items),
            extraction_status=extraction.extraction_status,
            warnings=extraction.warnings + metadata.warnings,
        )

        return JSONResponse(content={
            "extraction": result.model_dump(),
            "metadata": metadata.model_dump(),
            "provider": settings.llm_provider,
            "model": settings.llm_model,
        })
    finally:
        pdf_path.unlink(missing_ok=True)


@router.get("/health")
async def diagnostic_health():
    """Check LLM provider configuration and connectivity."""
    settings = get_settings()
    return {
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "timeout_seconds": settings.llm_timeout_seconds,
        "max_retries": settings.llm_max_retries,
        "api_key_configured": bool(settings.llm_api_key),
    }
