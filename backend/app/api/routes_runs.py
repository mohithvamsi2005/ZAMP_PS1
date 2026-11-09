"""Processing run APIs — Phase 6.

GET  /api/runs                  — paginated history with status filter
GET  /api/runs/{run_id}         — full run (status, decision, persisted results)
GET  /api/runs/{run_id}/events  — chronological stage events (live polling)
GET  /api/runs/{run_id}/result  — final decision + evidence once finished
POST /api/runs/{run_id}/retry   — re-queue a FAILED run (manual, single retry)
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Depends
from pydantic import BaseModel

from app.services.run_store import get_run, get_run_events, list_runs
from app.services.workflow import process_invoice_background, retry_failed_run
from app.core.security import require_write_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runs", tags=["runs"])


class RunSummary(BaseModel):
    run_id: str
    invoice_id: Optional[int] = None
    status: str
    decision: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


class RunsListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    runs: List[RunSummary]


class EventItem(BaseModel):
    id: int
    stage: str
    status: str
    message: Optional[str] = None
    details: dict = {}
    created_at: Optional[str] = None


class RunDetail(BaseModel):
    run_id: str
    invoice_id: Optional[int] = None
    status: str
    decision: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    extraction: Optional[dict] = None
    document_meta: Optional[dict] = None
    vendor_match: Optional[dict] = None
    po_match: Optional[dict] = None
    duplicate_check: Optional[dict] = None
    amount_validation: Optional[dict] = None
    line_item_validation: Optional[dict] = None
    tax_validation: Optional[dict] = None
    decision_result: Optional[dict] = None
    invoice: Optional[dict] = None
    events: List[EventItem] = []


class RunResultResponse(BaseModel):
    run_id: str
    status: str
    decision: Optional[str] = None
    error_message: Optional[str] = None
    invoice: Optional[dict] = None
    extraction: Optional[dict] = None
    document_meta: Optional[dict] = None
    vendor_match: Optional[dict] = None
    po_match: Optional[dict] = None
    duplicate_check: Optional[dict] = None
    amount_validation: Optional[dict] = None
    line_item_validation: Optional[dict] = None
    tax_validation: Optional[dict] = None
    decision_result: Optional[dict] = None


class RetryResponse(BaseModel):
    run_id: str
    status: str
    message: str


@router.get("", response_model=RunsListResponse, summary="List processing runs")
async def list_processing_runs(
    status: Optional[str] = Query(None, description="PENDING | RUNNING | COMPLETED | FAILED"),
    decision: Optional[str] = Query(None, description="APPROVE | REVIEW | REJECT"),
    invoice_id: Optional[int] = Query(None, description="Filter by invoice ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """Run history with basic pagination and filtering."""
    try:
        result = list_runs(
            status_filter=status,
            decision_filter=decision,
            invoice_id=invoice_id,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return RunsListResponse(**result)


@router.get("/{run_id}", response_model=RunDetail, summary="Get one run (full detail)")
async def get_processing_run(run_id: str):
    data = get_run(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Processing run {run_id} not found")
    return RunDetail(**data)


@router.get("/{run_id}/events", response_model=List[EventItem],
            summary="Get persisted stage events for a run")
async def get_run_events_endpoint(run_id: str):
    events = get_run_events(run_id)
    if events is None:
        raise HTTPException(status_code=404, detail=f"Processing run {run_id} not found")
    return [EventItem(**e) for e in events]


@router.get("/{run_id}/result", response_model=RunResultResponse,
            summary="Get final decision and evidence for a finished run")
async def get_run_result(run_id: str):
    data = get_run(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Processing run {run_id} not found")
    if data["status"] in ("PENDING", "RUNNING"):
        raise HTTPException(
            status_code=409,
            detail=f"Run is still {data['status']}; result not yet available",
        )
    return RunResultResponse(
        run_id=run_id,
        status=data["status"],
        decision=data["decision"],
        error_message=data["error_message"],
        invoice=data["invoice"],
        extraction=data["extraction"],
        document_meta=data["document_meta"],
        vendor_match=data["vendor_match"],
        po_match=data["po_match"],
        duplicate_check=data["duplicate_check"],
        amount_validation=data["amount_validation"],
        line_item_validation=data["line_item_validation"],
        tax_validation=data["tax_validation"],
        decision_result=data["decision_result"],
    )


@router.post("/{run_id}/retry", response_model=RetryResponse,
             summary="Re-queue a failed run for another processing attempt")
async def retry_run(
    run_id: str,
    background_tasks: BackgroundTasks = None,
    _access: None = Depends(require_write_access),
):
    data = get_run(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Processing run {run_id} not found")
    if data["status"] != "FAILED":
        raise HTTPException(
            status_code=409,
            detail=f"Only FAILED runs can be retried (current status: {data['status']})",
        )
    if not retry_failed_run(run_id):
        raise HTTPException(status_code=409, detail="Run could not be reset for retry")
    if background_tasks is not None:
        background_tasks.add_task(process_invoice_background, run_id, data["invoice_id"])
    return RetryResponse(
        run_id=run_id,
        status="PENDING",
        message="Run reset and queued for retry. Previous attempt history is preserved.",
    )
