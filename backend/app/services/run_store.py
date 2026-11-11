"""Read-side helpers for runs and invoices (API persistence sources).

All API responses are built from stored database records — no canned data.
Stored *_json columns are decoded to dicts; all monetary values are JSON-safe
strings. Raw document text is never returned by these helpers (count/hash/
status metadata only).
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text

from app.core.config import get_settings
from app.db.models import (
    Invoice, ProcessingRun, ProcessingRunEvent, InvoiceLine,
    ProcessingRunStatus, PurchaseOrder, PurchaseOrderLine, Vendor,
)
from app.db.session import SessionLocal, enable_sqlite_foreign_keys

logger = logging.getLogger(__name__)
_reset_lock = threading.Lock()


class ActiveRunConflictError(Exception):
    """Raised when a reset is attempted while runs are pending or running."""


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


# ── Phase 7 additions: enriched invoice list + dashboard summary ─────────────────


def _enriched_run(r: ProcessingRun, db) -> dict:
    """Compact run row joined with its invoice + vendor for history/activity lists."""
    inv = db.get(Invoice, r.invoice_id) if r.invoice_id else None
    vendor_name = None
    po_reference = None
    if inv is not None:
        if inv.vendor_id:
            vend = db.get(Vendor, inv.vendor_id)
            vendor_name = vend.legal_name if vend else None
        if inv.purchase_order_id:
            po = db.get(PurchaseOrder, inv.purchase_order_id)
            po_reference = po.po_number if po else None
    duration = None
    if r.started_at and r.completed_at:
        duration = (r.completed_at - r.started_at).total_seconds()
    return {
        "run_id": r.id,
        "invoice_id": r.invoice_id,
        "invoice_number": inv.invoice_number if inv else None,
        "vendor_name": vendor_name,
        "po_reference": po_reference,
        "total_amount": str(inv.total_amount) if inv and inv.total_amount is not None else None,
        "currency": inv.currency if inv else None,
        "original_filename": inv.original_filename if inv else None,
        "status": r.status.value if r.status else None,
        "decision": r.decision.value if r.decision else None,
        "error_message": r.error_message,
        "created_at": _iso(r.created_at),
        "started_at": _iso(r.started_at),
        "completed_at": _iso(r.completed_at),
        "duration_seconds": duration,
    }


def list_invoices(
    search: Optional[str] = None,
    decision_filter: Optional[str] = None,
    status_filter: Optional[str] = None,
    sort_by: str = "submission",
    sort_dir: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Paginated invoice history with join context (vendor, PO, latest run).

    Filters apply to the LATEST processing run for each invoice (the invoice's
    current outcome). Sorting is explicit (whitelisted columns only).
    Filter logic is intentionally implemented in Python over the full table
    (PS-1 invoice volumes are small); push to SQL window functions if the
    dataset grows beyond a few thousand invoices.
    """
    sort_by = (sort_by or "submission").lower()
    sort_dir = (sort_dir or "desc").lower()
    if sort_by not in ("submission", "total_amount"):
        sort_by = "submission"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"

    direction = decision_filter.upper() if decision_filter else None
    if direction and direction not in ("APPROVE", "REVIEW", "REJECT"):
        raise ValueError(f"Invalid decision filter: {decision_filter!r}")
    sd = status_filter.upper() if status_filter else None
    if sd and sd not in ("PENDING", "RUNNING", "COMPLETED", "FAILED"):
        raise ValueError(f"Invalid status filter: {status_filter!r}")

    db = SessionLocal()
    try:
        query = db.query(Invoice)
        if search and search.strip():
            query = query.filter(Invoice.invoice_number.ilike(f"%{search.strip()}%"))
        invoices = query.all()

        ids = [inv.id for inv in invoices]
        latest: dict[int, ProcessingRun] = {}
        if ids:
            for r in db.query(ProcessingRun).filter(ProcessingRun.invoice_id.in_(ids)).all():
                cur = latest.get(r.invoice_id)
                if cur is None:
                    latest[r.invoice_id] = r
                    continue
                left = (r.created_at, r.id)
                right = (cur.created_at, cur.id)
                if left > right:
                    latest[r.invoice_id] = r

        vendor_ids = {inv.vendor_id for inv in invoices if inv.vendor_id}
        po_ids = {inv.purchase_order_id for inv in invoices if inv.purchase_order_id}
        vendors = (
            {v.id: v for v in db.query(Vendor).filter(Vendor.id.in_(vendor_ids)).all()}
            if vendor_ids else {}
        )
        pos = (
            {p.id: p for p in db.query(PurchaseOrder).filter(PurchaseOrder.id.in_(po_ids)).all()}
            if po_ids else {}
        )

        items = []
        for inv in invoices:
            r = latest.get(inv.id)
            r_decision = r.decision.value if (r and r.decision) else None
            r_status = r.status.value if r else None
            if direction and r_decision != direction:
                continue
            if sd and r_status != sd:
                continue
            vend = vendors.get(inv.vendor_id) if inv.vendor_id else None
            po = pos.get(inv.purchase_order_id) if inv.purchase_order_id else None
            items.append({
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "vendor_name": vend.legal_name if vend else None,
                "po_reference": po.po_number if po else None,
                "total_amount": str(inv.total_amount) if inv.total_amount is not None else None,
                "currency": inv.currency,
                "original_filename": inv.original_filename,
                "file_sha256": inv.file_sha256,
                "created_at": _iso(inv.created_at),
                "last_run_id": r.id if r else None,
                "last_run_status": r_status,
                "last_run_decision": r_decision,
            })

        if sort_by == "total_amount":
            def _key(it):
                try:
                    return Decimal(it["total_amount"] or "0")
                except (InvalidOperation, TypeError, ValueError):
                    return Decimal("0")
        else:
            def _key(it):
                return it["created_at"] or ""
        items.sort(key=_key, reverse=(sort_dir == "desc"))

        total = len(items)
        start = (page - 1) * page_size
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "invoices": items[start:start + page_size],
        }
    finally:
        db.close()


def get_dashboard_summary() -> dict:
    """Aggregate dashboard metrics from live database records only."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func
    db = SessionLocal()
    try:
        total_invoices = db.query(func.count(Invoice.id)).scalar() or 0
        total_runs = db.query(func.count(ProcessingRun.id)).scalar() or 0

        runs_by_status = {
            row[0].value if row[0] is not None else None: row[1]
            for row in db.query(ProcessingRun.status, func.count(ProcessingRun.id))
            .group_by(ProcessingRun.status)
            .all()
        }
        decisions_raw = {
            row[0].value if row[0] is not None else None: row[1]
            for row in db.query(ProcessingRun.decision, func.count(ProcessingRun.id))
            .filter(ProcessingRun.decision.isnot(None))
            .group_by(ProcessingRun.decision)
            .all()
        }

        completed_runs = runs_by_status.get("COMPLETED", 0)
        failed_runs = runs_by_status.get("FAILED", 0)
        pending_runs = runs_by_status.get("PENDING", 0)
        running_runs = runs_by_status.get("RUNNING", 0)

        approved = decisions_raw.get("APPROVE", 0)
        review = decisions_raw.get("REVIEW", 0)
        rejected = decisions_raw.get("REJECT", 0)
        decision_total = approved + review + rejected
        approval_rate = round((approved / decision_total) * 100, 1) if decision_total else None

        avg_duration = (
            db.query(
                func.avg(
                    (func.julianday(ProcessingRun.completed_at) - func.julianday(ProcessingRun.started_at))
                    * 86400.0
                )
            )
            .filter(ProcessingRun.started_at.isnot(None), ProcessingRun.completed_at.isnot(None))
            .scalar()
        )
        avg_processing_seconds = round(float(avg_duration), 1) if avg_duration is not None else None

        since = datetime.now(timezone.utc).date() - timedelta(days=13)
        activity_rows = (
            db.query(
                func.date(Invoice.created_at).label("day"),
                func.count(Invoice.id).label("submitted"),
            )
            .filter(Invoice.created_at >= datetime(since.year, since.month, since.day))
            .group_by(func.date(Invoice.created_at))
            .all()
        )
        submitted_by_day = {row.day: row.submitted for row in activity_rows}
        activity = []
        for offset in range(13, -1, -1):
            day = (datetime.now(timezone.utc).date() - timedelta(days=offset)).isoformat()
            activity.append({"date": day, "submitted": int(submitted_by_day.get(day, 0))})

        recent = (
            db.query(ProcessingRun)
            .order_by(ProcessingRun.created_at.desc(), ProcessingRun.id.desc())
            .limit(8)
            .all()
        )
        recent_runs = [_enriched_run(r, db) for r in recent]

        failed = (
            db.query(ProcessingRun)
            .filter(ProcessingRun.status == ProcessingRunStatus.FAILED)
            .order_by(ProcessingRun.created_at.desc(), ProcessingRun.id.desc())
            .limit(5)
            .all()
        )
        latest_failed = [_enriched_run(r, db) for r in failed]

        return {
            "totals": {
                "invoices": int(total_invoices),
                "runs": int(total_runs),
                "completed_runs": int(completed_runs),
                "failed_runs": int(failed_runs),
                "pending_runs": int(pending_runs),
                "running_runs": int(running_runs),
            },
            "decisions": {
                "APPROVE": int(approved),
                "REVIEW": int(review),
                "REJECT": int(rejected),
            },
            "decision_total": int(decision_total),
            "approval_rate": approval_rate,
            "review_queue": int(review),
            "avg_processing_seconds": avg_processing_seconds,
            "activity_last_14_days": activity,
            "recent_runs": recent_runs,
            "latest_failed_runs": latest_failed,
        }
    finally:
        db.close()


def reset_demo_data() -> dict:
    """Clear active database records, remove scoped uploads, and re-seed baseline data."""
    from app.db.seed import seed

    settings = get_settings()
    with _reset_lock:
        db = SessionLocal()
        try:
            enable_sqlite_foreign_keys(db)
            active_runs = (
                db.query(ProcessingRun)
                .filter(ProcessingRun.status.in_([ProcessingRunStatus.PENDING, ProcessingRunStatus.RUNNING]))
                .count()
            )
            if active_runs:
                raise ActiveRunConflictError(
                    "Cannot reset data while a processing run is queued or in progress."
                )

            storage_paths = [
                row[0]
                for row in db.query(Invoice.storage_path)
                .filter(Invoice.storage_path.isnot(None))
                .all()
            ]

            db.query(ProcessingRunEvent).delete(synchronize_session=False)
            db.query(ProcessingRun).delete(synchronize_session=False)
            db.query(InvoiceLine).delete(synchronize_session=False)
            db.query(Invoice).delete(synchronize_session=False)
            db.query(PurchaseOrderLine).delete(synchronize_session=False)
            db.query(PurchaseOrder).delete(synchronize_session=False)
            db.query(Vendor).delete(synchronize_session=False)

            if settings.database_url.startswith("sqlite"):
                seq_exists = db.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'")
                ).fetchone()
                if seq_exists:
                    db.execute(
                        text(
                            "DELETE FROM sqlite_sequence WHERE name IN "
                            "('vendors','purchase_orders','purchase_order_lines','invoices','invoice_lines','run_events')"
                        )
                    )

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        try:
            upload_base = Path(settings.upload_dir).resolve()
        except (OSError, RuntimeError):
            upload_base = None

        deleted_files = 0
        if upload_base is not None:
            for raw_path in set(storage_paths):
                if not raw_path:
                    continue
                try:
                    candidate = Path(raw_path).resolve()
                except (OSError, RuntimeError):
                    continue
                if candidate != upload_base and upload_base in candidate.parents and candidate.is_file():
                    try:
                        candidate.unlink(missing_ok=True)
                        deleted_files += 1
                    except OSError:
                        logger.warning("Failed to remove uploaded file during reset: %s", candidate)

        seed()

        verify_db = SessionLocal()
        try:
            return {
                "status": "ok",
                "invoices": int(verify_db.query(Invoice).count()),
                "runs": int(verify_db.query(ProcessingRun).count()),
                "vendors": int(verify_db.query(Vendor).count()),
                "purchase_orders": int(verify_db.query(PurchaseOrder).count()),
                "deleted_files": deleted_files,
                "message": "Workspace reset to seeded baseline.",
            }
        finally:
            verify_db.close()
