"""Invoice upload + invoice detail APIs — Phase 6.

POST /api/invoices/upload   — multipart PDF upload, 202 Accepted
GET  /api/invoices/{id}     — invoice submission record + run history

The uploaded filename is preserved as metadata only and never used as a
filesystem path. Storage uses generated server-side names under UPLOAD_DIR
(kept outside any public/static directory).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.config import get_settings
from app.services.workflow import create_invoice_and_run, process_invoice_background
from app.services.run_store import get_invoice, list_invoices
from app.services.pdf_extractor import validate_pdf
from app.db.session import SessionLocal
from app.db.models import Invoice

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


class InvoiceListItem(BaseModel):
    id: int
    invoice_number: Optional[str] = None
    vendor_name: Optional[str] = None
    po_reference: Optional[str] = None
    total_amount: Optional[str] = None
    currency: Optional[str] = None
    original_filename: Optional[str] = None
    file_sha256: Optional[str] = None
    created_at: Optional[str] = None
    last_run_id: Optional[str] = None
    last_run_status: Optional[str] = None
    last_run_decision: Optional[str] = None


class InvoiceListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    invoices: List[InvoiceListItem]


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
    "",
    response_model=InvoiceListResponse,
    summary="List invoices (history, enriched with latest run outcome)",
)
async def list_invoices_endpoint(
    search: Optional[str] = Query(None, description="Substring match on invoice number"),
    decision: Optional[str] = Query(None, description="APPROVE | REVIEW | REJECT"),
    status: Optional[str] = Query(None, description="PENDING | RUNNING | COMPLETED | FAILED"),
    sort_by: str = Query("submission", description="submission | total_amount"),
    sort_dir: str = Query("desc", description="asc | desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """Enriched invoice history with server-side pagination and filtering.

    Filters apply to the invoice's LATEST run (its current outcome).
    """
    try:
        result = list_invoices(
            search=search,
            decision_filter=decision,
            status_filter=status,
            sort_by=sort_by,
            sort_dir=sort_dir,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return InvoiceListResponse(**result)


@router.get(
    "/{invoice_id}/document",
    summary="Serve the uploaded invoice PDF (inline)",
)
async def get_invoice_document(invoice_id: int):
    """Stream the stored PDF for the given invoice.

    The served path comes ONLY from the invoice row created at upload time —
    there is no user-controlled path input, and the response filename never
    contains the user-supplied original filename (path traversal / header
    injection are out of the threat model here).
    """
    db = SessionLocal()
    try:
        inv = db.get(Invoice, invoice_id)
    finally:
        db.close()
    if inv is None:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
    if not inv.storage_path:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} has no stored document")
    path = Path(inv.storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} document is missing on disk")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"invoice_{inv.id}.pdf",
        headers={"Content-Disposition": f'inline; filename="invoice_{inv.id}.pdf"'},
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
