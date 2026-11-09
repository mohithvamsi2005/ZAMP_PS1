"""Invoice upload + invoice detail APIs — Phase 6.

POST /api/invoices/upload   — multipart PDF upload, 202 Accepted
GET  /api/invoices/{id}     — invoice submission record + run history

The uploaded filename is preserved as metadata only and never used as a
filesystem path. Storage uses generated server-side names under UPLOAD_DIR
(kept outside any public/static directory).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.config import get_settings
from app.services.workflow import create_invoice_and_run, process_invoice_background
from app.services.run_store import get_invoice
from app.services.pdf_extractor import validate_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/invoices", tags=["invoices"])


# ── Response schemas ───────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    invoice_id: int
    run_id: str
    status: str
    message: str


class InvoiceLineOut(BaseModel):
    id: int
    description: str
    sku: Optional[str] = None
    quantity: Optional[str] = None
    unit: Optional[str] = None
    unit_price: Optional[str] = None
    line_total: Optional[str] = None


class RunBrief(BaseModel):
    run_id: str
    status: str
    decision: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


class InvoiceDetail(BaseModel):
    id: int
    invoice_number: Optional[str] = None
    vendor_id: Optional[int] = None
    purchase_order_id: Optional[int] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    currency: Optional[str] = None
    subtotal: Optional[str] = None
    tax_amount: Optional[str] = None
    discount_amount: Optional[str] = None
    total_amount: Optional[str] = None
    original_filename: Optional[str] = None
    file_sha256: Optional[str] = None
    created_at: Optional[str] = None
    line_items: List[InvoiceLineOut] = []
    processing_runs: List[RunBrief] = []


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=202,
    summary="Upload an invoice PDF and queue processing",
)
async def upload_invoice(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
):
    """Accept a multipart PDF upload, create the invoice + run records and
    start background processing. Poll GET /api/runs/{run_id} for live status.
    """
    settings = get_settings()
    max_bytes = settings.max_upload_mb * 1024 * 1024

    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds {settings.max_upload_mb} MB limit",
        )

    # Structural validation (magic bytes / size) before anything is persisted.
    import tempfile, os
    from pathlib import Path
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix="zamp_validate_")
    validation_errors: List[str] = []
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(contents)
        validation_errors = validate_pdf(Path(tmp_path), max_upload_mb=settings.max_upload_mb)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    if validation_errors:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid PDF: {'; '.join(validation_errors)}",
        )

    try:
        invoice_id, run_id = create_invoice_and_run(contents, filename, settings)
    except Exception as exc:
        logger.error("Upload failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create processing record: {exc}",
        )

    # Background task gets identifiers only — never the request-scoped DB session.
    if background_tasks is not None:
        background_tasks.add_task(process_invoice_background, run_id, invoice_id)

    return UploadResponse(
        invoice_id=invoice_id,
        run_id=run_id,
        status="PENDING",
        message="Invoice uploaded and queued for processing.",
    )


@router.get(
    "/{invoice_id}",
    response_model=InvoiceDetail,
    summary="Get an invoice submission and its run history",
)
async def get_invoice_endpoint(invoice_id: int):
    data = get_invoice(invoice_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
    return InvoiceDetail(**data)
