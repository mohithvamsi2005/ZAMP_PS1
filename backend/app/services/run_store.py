"""Read-side helpers for runs and invoices (API persistence sources).

All API responses are built from stored database records — no canned data.
Stored *_json columns are decoded to dicts; all monetary values are JSON-safe
strings. Raw document text is never returned by these helpers (count/hash/
status metadata only).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from app.db.models import (
    Invoice, ProcessingRun, ProcessingRunEvent, InvoiceLine,
    ProcessingRunStatus,
)
from app.db.session import SessionLocal


def _loads(raw: Optional[str], default=None) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def _invoice_payload(inv: Invoice, db) -> dict:
    return {
        "id": inv.id,
        "invoice_number": inv.invoice_number,
        "vendor_id": inv.vendor_id,
        "purchase_order_id": inv.purchase_order_id,
        "invoice_date": _iso(inv.invoice_date),
        "due_date": _iso(inv.due_date),
        "currency": inv.currency,
        "subtotal": str(inv.subtotal) if inv.subtotal is not None else None,
        "tax_amount": str(inv.tax_amount) if inv.tax_amount is not None else None,
        "discount_amount": str(inv.discount_amount) if inv.discount_amount is not None else None,
        "total_amount": str(inv.total_amount) if inv.total_amount is not None else None,
        "original_filename": inv.original_filename,
        "file_sha256": inv.file_sha256,
        "created_at": _iso(inv.created_at),
        "line_items": [
            {
                "id": li.id,
                "description": li.description,
                "sku": li.sku,
                "quantity": str(li.quantity) if li.quantity is not None else None,
                "unit": li.unit,
                "unit_price": str(li.unit_price) if li.unit_price is not None else None,
                "line_total": str(li.line_total) if li.line_total is not None else None,
            }
            for li in db.query(InvoiceLine)
            .filter(InvoiceLine.invoice_id == inv.id)
            .order_by(InvoiceLine.id)
            .all()
        ],
    }


def _event_payload(ev: ProcessingRunEvent) -> dict:
    return {
        "id": ev.id,
        "stage": ev.stage,
        "status": ev.status.value,
        "message": ev.message,
        "details": _loads(ev.details_json, {}) or {},
        "created_at": _iso(ev.created_at),
    }


def get_run(run_id: str) -> Optional[dict]:
    """Full run record: status, decision, all persisted stage results, events."""
    db = SessionLocal()
    try:
        run = db.get(ProcessingRun, run_id)
        if run is None:
            return None
        events = (
            db.query(ProcessingRunEvent)
            .filter(ProcessingRunEvent.processing_run_id == run_id)
            .order_by(ProcessingRunEvent.created_at, ProcessingRunEvent.id)
            .all()
        )
        inv = db.get(Invoice, run.invoice_id) if run.invoice_id else None
        return {
            "run_id": run.id,
            "invoice_id": run.invoice_id,
            "status": run.status.value if run.status else None,
            "decision": run.decision.value if run.decision else None,
            "llm_provider": run.llm_provider,
            "llm_model": run.llm_model,
            "started_at": _iso(run.started_at),
            "completed_at": _iso(run.completed_at),
            "error_message": run.error_message,
            "created_at": _iso(run.created_at),
            "extraction": _loads(run.extraction_json),
            "document_meta": _loads(run.document_meta_json),
            "vendor_match": _loads(run.vendor_match_json),
            "po_match": _loads(run.po_match_json),
            "duplicate_check": _loads(run.duplicate_check_json),
            "amount_validation": _loads(run.amount_validation_json),
            "line_item_validation": _loads(run.line_item_validation_json),
            "tax_validation": _loads(run.tax_validation_json),
            "decision_result": _loads(run.decision_json),
            "invoice": _invoice_payload(inv, db) if inv is not None else None,
            "events": [_event_payload(e) for e in events],
        }
    finally:
        db.close()


def get_run_events(run_id: str) -> Optional[list[dict]]:
    """Chronological persisted events for a run; None when the run is unknown."""
    db = SessionLocal()
    try:
        run = db.get(ProcessingRun, run_id)
        if run is None:
            return None
        events = (
            db.query(ProcessingRunEvent)
            .filter(ProcessingRunEvent.processing_run_id == run_id)
            .order_by(ProcessingRunEvent.created_at, ProcessingRunEvent.id)
            .all()
        )
        return [_event_payload(e) for e in events]
    finally:
        db.close()


def list_runs(
    status_filter: Optional[str] = None,
    decision_filter: Optional[str] = None,
    invoice_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Paginated run history with optional status/decision/invoice filters."""
    db = SessionLocal()
    try:
        query = db.query(ProcessingRun)
        if status_filter:
            try:
                query = query.filter(ProcessingRun.status == ProcessingRunStatus(status_filter.upper()))
            except ValueError:
                raise ValueError(f"Invalid status filter: {status_filter!r}")
        if decision_filter:
            query = query.filter(ProcessingRun.decision == decision_filter.upper())
        if invoice_id is not None:
            query = query.filter(ProcessingRun.invoice_id == invoice_id)

        total = query.count()
        runs = (
            query.order_by(ProcessingRun.created_at.desc(), ProcessingRun.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "runs": [
                {
                    "run_id": r.id,
                    "invoice_id": r.invoice_id,
                    "status": r.status.value,
                    "decision": r.decision.value if r.decision else None,
                    "llm_provider": r.llm_provider,
                    "llm_model": r.llm_model,
                    "created_at": _iso(r.created_at),
                    "started_at": _iso(r.started_at),
                    "completed_at": _iso(r.completed_at),
                    "error_message": r.error_message,
                }
                for r in runs
            ],
        }
    finally:
        db.close()


def get_invoice(invoice_id: int) -> Optional[dict]:
    """Invoice submission record with all of its processing runs."""
    db = SessionLocal()
    try:
        inv = db.get(Invoice, invoice_id)
        if inv is None:
            return None
        runs = (
            db.query(ProcessingRun)
            .filter(ProcessingRun.invoice_id == invoice_id)
            .order_by(ProcessingRun.created_at.desc())
            .all()
        )
        return {
            **_invoice_payload(inv, db),
            "processing_runs": [
                {
                    "run_id": r.id,
                    "status": r.status.value,
                    "decision": r.decision.value if r.decision else None,
                    "created_at": _iso(r.created_at),
                    "completed_at": _iso(r.completed_at),
                    "error_message": r.error_message,
                }
                for r in runs
            ],
        }
    finally:
        db.close()
