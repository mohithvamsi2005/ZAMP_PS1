"""Invoice processing workflow orchestrator — Phase 6.

Coordinates the full backend pipeline using the existing Phase 3–5 services:

    upload → document/PDF extraction → OCR (when applicable) → LLM extraction
    → vendor matching → PO matching → duplicate detection → amount validation
    → line-item validation → tax/arithmetic validation → deterministic decision
    → result persistence.

This module wires components together only; all business logic lives in the
individual services (pdf_extractor, ocr_service, llm_extractor, vendor_matcher,
po_matcher, duplicate_detector, amount_validator, line_item_validator,
tax_validator, decision_engine).

Background execution limitations (single-instance MVP):
  * FastAPI BackgroundTasks runs in-process. Jobs die with the server process,
    are not distributed, and are not retried automatically.
  * SQLite serialises writes; heavy parallel processing can cause
    "database is locked" (mitigated with a 30s busy timeout, not eliminated).
  * A run is claimed atomically (PENDING → RUNNING) so a second worker cannot
    double-process the same run.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.decision_policy import DEFAULT_POLICY
from app.db.models import (
    Invoice, InvoiceLine, ProcessingRun, ProcessingRunEvent,
    ProcessingRunStatus, PurchaseOrder, RunEventStatus, Vendor,
)
from app.db.session import SessionLocal
from app.schemas.decision import DecisionInput, DecisionResult
from app.schemas.invoice import ExtractionMetadata, InvoiceExtraction
from app.schemas.matching import (
    AmountValidationResult, DuplicateResult, LineItemValidationResult,
    POMatchResult, TaxValidationResult, VendorMatchResult,
)
from app.services.amount_validator import validate_amount
from app.services.decision_engine import decide
from app.services.duplicate_detector import detect_duplicates
from app.services.line_item_validator import validate_line_items
from app.services.llm_extractor import extract_invoice_from_text
from app.services.pdf_extractor import extract_pdf
from app.services.po_matcher import match_po
from app.services.tax_validator import validate_tax_arithmetic
from app.services.vendor_matcher import match_vendor

logger = logging.getLogger(__name__)


# ── Stage constants ───────────────────────────────────────────────────────────

STAGE_RECEIVED = "RECEIVED"
STAGE_DOCUMENT_PROCESSING = "DOCUMENT_PROCESSING"
STAGE_OCR_PROCESSING = "OCR_PROCESSING"
STAGE_LLM_EXTRACTION = "LLM_EXTRACTION"
STAGE_VENDOR_MATCHING = "VENDOR_MATCHING"
STAGE_PO_MATCHING = "PO_MATCHING"
STAGE_DUPLICATE_CHECK = "DUPLICATE_CHECK"
STAGE_AMOUNT_VALIDATION = "AMOUNT_VALIDATION"
STAGE_LINE_ITEM_VALIDATION = "LINE_ITEM_VALIDATION"
STAGE_TAX_VALIDATION = "TAX_VALIDATION"
STAGE_DECISION = "DECISION"
STAGE_PERSISTENCE = "PERSISTENCE"
STAGE_COMPLETED = "COMPLETED"
STAGE_FAILED = "FAILED"

VALID_STAGES = {
    STAGE_RECEIVED, STAGE_DOCUMENT_PROCESSING, STAGE_OCR_PROCESSING,
    STAGE_LLM_EXTRACTION, STAGE_VENDOR_MATCHING, STAGE_PO_MATCHING,
    STAGE_DUPLICATE_CHECK, STAGE_AMOUNT_VALIDATION, STAGE_LINE_ITEM_VALIDATION,
    STAGE_TAX_VALIDATION, STAGE_DECISION, STAGE_PERSISTENCE,
    STAGE_COMPLETED, STAGE_FAILED,
}

# Fields that must be present (and evidenced) for APPROVE eligibility
_CRITICAL_FIELDS = ("invoice_number", "vendor_name", "total_amount")


# ── Small helpers ─────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dumps(data: Any) -> str:
    """JSON-serialise anything (Decimal, datetime, enums…) deterministically."""
    return json.dumps(data, default=str, sort_keys=True)


def _safe_decimal(value) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _safe_filename_suffix(original_filename: str) -> str:
    """Extract a sanitised extension (never the user-supplied path itself)."""
    suffix = Path(original_filename or "").suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,7}", suffix):
        return suffix
    return ".pdf"


def save_uploaded_pdf(upload_dir: Path, contents: bytes, original_filename: str) -> tuple[Path, str]:
    """Persist uploaded bytes under a generated server-side filename.

    The original filename is metadata only and is never used as a filesystem
    path. Returns (storage_path, sha256_hex).
    """
    upload_dir.mkdir(parents=True, exist_ok=True)
    sha256_hex = None
    import hashlib
    sha256_hex = hashlib.sha256(contents).hexdigest()
    stem = f"{secrets.token_hex(8)}_{sha256_hex[:16]}"
    dest = upload_dir / f"{stem}{_safe_filename_suffix(original_filename)}"
    counter = 0
    while dest.exists():
        counter += 1
        dest = upload_dir / f"{stem}_{counter}{_safe_filename_suffix(original_filename)}"
    dest.write_bytes(contents)
    return dest, sha256_hex


def _event(
    run_id: str,
    db: Session,
    stage: str,
    status: RunEventStatus,
    message: str,
    details: Optional[dict] = None,
) -> None:
    """Persist one stage event and commit immediately.

    Committing per event means another API request can read the run's progress
    while processing is still running. Events never contain raw document text —
    only counts, statuses, hashes and identifiers.
    """
    ev = ProcessingRunEvent(
        processing_run_id=run_id,
        stage=stage,
        status=status,
        message=message,
        details_json=_dumps(details or {}),
        created_at=_now(),
    )
    db.add(ev)
    db.commit()
    logger.info("run %s stage=%s status=%s: %s", run_id, stage, status.value, message)


def _fail_run(
    run_id: str,
    db: Session,
    failed_stage: str,
    error_message: str,
    details: Optional[dict] = None,
    prior_status: Optional[str] = None,
) -> None:
    """Mark a run FAILED for a technical failure and record an event.

    Prior completed events are preserved; status transitions RUNNING → FAILED.
    A technical failure never writes a business decision.
    """
    try:
        db.rollback()  # discard any dirty state from the failed stage
        run = db.get(ProcessingRun, run_id)
        if run is not None and str(run.status) not in ("FAILED", "COMPLETED"):
            run.status = ProcessingRunStatus.FAILED
            run.error_message = error_message
            if not run.started_at:
                run.started_at = _now()
            db.commit()
        _event(run_id, db, STAGE_FAILED, RunEventStatus.FAILED, f"{failed_stage}: {error_message}", details)
    except Exception:
        logger.exception("Could not persist FAILED state for run %s", run_id)
        db.rollback()


def _missing_critical_fields(extraction: InvoiceExtraction) -> list[str]:
    missing = []
    for field in _CRITICAL_FIELDS:
        val = getattr(extraction, field, None)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(field)
    return missing


def _min_extraction_confidence(extraction: InvoiceExtraction) -> Optional[float]:
    """Minimum model-reported confidence across non-null critical fields.

    Critical values include monetary Decimals (total_amount), which the LLM may
    represent as strings in evidence. Returns None when the extraction carries
    no confidence at all (e.g. older prompt outputs).
    """
    confidences: list[float] = []
    for field in _CRITICAL_FIELDS:
        val = getattr(extraction, field)
        if val is None or (isinstance(val, str) and not val.strip()):
            continue
        ev = (extraction.evidence or {}).get(field)
        if isinstance(ev, dict) and ev.get("confidence") is not None:
            try:
                confidences.append(float(ev["confidence"]))
            except (TypeError, ValueError):
                continue
    return min(confidences) if confidences else None


# ══════════════════════════════════════════════════════════════════════════════
# Upload — creates the invoice submission record and processing run
# ══════════════════════════════════════════════════════════════════════════════

def create_invoice_and_run(
    contents: bytes,
    original_filename: str,
    settings=None,
) -> tuple[int, str]:
    """Create an Invoice row + PENDING ProcessingRun (and the storage file).

    Returns (invoice_id, run_id). The run stays PENDING until the background
    worker atomically claims it (PENDING → RUNNING).
    """
    if settings is None:
        settings = get_settings()
    db = SessionLocal()
    try:
        pdf_path, sha256_hex = save_uploaded_pdf(
            Path(settings.upload_dir), contents, original_filename,
        )

        inv = Invoice(
            original_filename=original_filename,  # metadata only, never a path
            storage_path=str(pdf_path),
            file_sha256=sha256_hex,
            created_at=_now(),
        )
        db.add(inv)
        db.flush()  # assign inv.id without opening a long transaction

        run_id = str(uuid4())
        run = ProcessingRun(
            id=run_id,
            invoice_id=inv.id,
            status=ProcessingRunStatus.PENDING,
            created_at=_now(),
        )
        db.add(run)
        db.commit()

        _event(
            run_id, db, STAGE_RECEIVED, RunEventStatus.COMPLETED,
            f"Invoice uploaded and queued: {original_filename} "
            f"(sha256 {sha256_hex[:16]}…, {len(contents)} bytes)",
            {"original_filename": original_filename, "sha256": sha256_hex, "size_bytes": len(contents)},
        )
        return inv.id, run_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# Orchestration stage functions (one per pipeline step — no giant function)
# ══════════════════════════════════════════════════════════════════════════════

def _stage_document_processing(
    run_id: str, db: Session, pdf_path: Path,
) -> tuple[ExtractionMetadata, str]:
    """Stage 1 — PDF text extraction via PyMuPDF (Phase 3 service)."""
    _event(run_id, db, STAGE_DOCUMENT_PROCESSING, RunEventStatus.RUNNING,
           f"Extracting PDF text: {pdf_path.name}")
    metadata, full_text = extract_pdf(pdf_path)
    _event(
        run_id, db, STAGE_DOCUMENT_PROCESSING, RunEventStatus.COMPLETED,
        f"PDF text extracted: {metadata.page_count} page(s), "
        f"{metadata.total_chars_extracted} chars",
        {
            "page_count": metadata.page_count,
            "total_chars_extracted": metadata.total_chars_extracted,
            "document_hash": metadata.document_hash,
            "pages": metadata.pages_processed,
            "warnings": metadata.warnings,
        },
    )
    if not metadata.source_pages:
        metadata.source_pages = [p["page"] for p in metadata.pages_processed]
    return metadata, full_text


def _stage_ocr(
    run_id: str, db: Session, pdf_path: Path,
    metadata: ExtractionMetadata, full_text: str,
) -> str:
    """Stage 2 — OCR fallback for pages without a usable text layer.

    Reuses Phase 3's OCRService; non-fatal when other pages carry digital text
    (result downgraded honestly — see doc-level failure check below).
    """
    ocr_pages = [pm["page"] for pm in metadata.pages_processed
                 if pm.get("method") == "OCR_REQUIRED"]
    if not ocr_pages:
        _event(run_id, db, STAGE_OCR_PROCESSING, RunEventStatus.SKIPPED,
               "OCR not required — all pages have a digital text layer",
               {"skipped_reason": "no OCR_REQUIRED pages"})
        return full_text

    _event(run_id, db, STAGE_OCR_PROCESSING, RunEventStatus.RUNNING,
           f"Running OCR on {len(ocr_pages)} page(s)")
    from app.services.ocr_service import OCRService
    ocr = OCRService()
    ocr_failures = []
    for pg in ocr_pages:
        try:
            text_chunk, confidence = ocr.ocr_page(pg - 1, pdf_path)
            for pm in metadata.pages_processed:
                if pm["page"] == pg:
                    pm["method"] = "OCR"
                    pm["confidence"] = confidence
                    pm["ocr_char_count"] = len(text_chunk)
            if text_chunk.strip():
                full_text = full_text.replace(
                    f"--- PAGE {pg} ---\n", f"--- PAGE {pg} (OCR) ---\n{text_chunk}\n",
                )
                # The page recovered via OCR — its initial "no extractable text"
                # warning is obsolete now and must not trigger EXTRACTION_001.
                metadata.warnings = [
                    w for w in metadata.warnings
                    if not (w.startswith(f"Page {pg}:")
                            and ("no extractable text" in w or "low text yield" in w))
                ]
        except Exception as exc:  # per-page failure is a warning, not fatal
            ocr_failures.append(f"page {pg}: {exc}")
    metadata.warnings.extend(f"OCR incomplete: {f}" for f in ocr_failures)

    if ocr_failures and not full_text.strip():
        raise RuntimeError(f"OCR failed and no digital text is available: {'; '.join(ocr_failures)}")

    if ocr_failures:
        _event(run_id, db, STAGE_OCR_PROCESSING, RunEventStatus.FAILED,
               f"OCR partially failed (continuing with available text): {'; '.join(ocr_failures)}",
               {"failed_pages": ocr_failures})
    else:
        _event(run_id, db, STAGE_OCR_PROCESSING, RunEventStatus.COMPLETED,
               f"OCR completed for {len(ocr_pages)} page(s)",
               {"ocr_pages": ocr_pages})
    return full_text


def _stage_llm_extraction(
    run_id: str, db: Session, full_text: str, metadata: ExtractionMetadata,
) -> InvoiceExtraction:
    """Stage 3 — LLM structured extraction (Phase 3 service + Pydantic validation)."""
    _event(run_id, db, STAGE_LLM_EXTRACTION, RunEventStatus.RUNNING,
           f"Running LLM extraction ({len(full_text)} chars of document text)")

    # No transaction is open across the (potentially slow) LLM call.
    db.commit()
    extraction = extract_invoice_from_text(full_text, metadata)

    _event(
        run_id, db, STAGE_LLM_EXTRACTION,
        RunEventStatus.COMPLETED if extraction.extraction_status in ("SUCCESS", "PARTIAL")
        else RunEventStatus.FAILED,
        f"LLM extraction {extraction.extraction_status}: "
        f"{len(extraction.line_items)} line item(s), "
        f"{len(extraction.warnings)} warning(s)",
        {"extraction_status": extraction.extraction_status, "warnings": extraction.warnings[:10]},
    )
    return extraction


_CENTS = Decimal("0.01")
_FOUR_DP = Decimal("0.0001")


def _persist_extraction(
    db: Session, inv: Invoice, extraction: InvoiceExtraction,
) -> None:
    """Write extracted fields + line items onto the invoice row.

    Line items are deleted and re-created, so a retried run over the same
    invoice never duplicates rows.

    Line items whose LLM-provided fields are incomplete are handled by
    deterministic arithmetic instead of fabrication:

    * line_total  = quantity * unit_price   (when the first two exist)
    * unit_price  = line_total / quantity   (when the first two exist)
    * quantity    = line_total / unit_price (when the first two exist)

    A line where fewer than two of the three are known cannot be persisted
    honestly — it is skipped and a warning is appended to the extraction so
    the decision engine routes the invoice to human review
    (EXTRACTION_001 / LINEITEM_001) instead of crashing the whole run.
    """
    inv.invoice_number = extraction.invoice_number
    inv.currency = extraction.currency
    inv.subtotal = _safe_decimal(extraction.subtotal)
    inv.tax_amount = _safe_decimal(extraction.tax_amount)
    inv.discount_amount = _safe_decimal(extraction.discount_amount)
    inv.total_amount = _safe_decimal(extraction.total_amount)
    inv.invoice_date = None
    if extraction.invoice_date:
        try:
            inv.invoice_date = datetime.fromisoformat(extraction.invoice_date).replace(tzinfo=timezone.utc)
        except ValueError:
            pass  # malformed date stays None — extraction warnings carry the signal

    for li in list(inv.line_items):
        db.delete(li)
    db.flush()

    skipped_lines = 0
    for li in extraction.line_items:
        if not (li.description and str(li.description).strip()):
            continue
        quantity = _safe_decimal(li.quantity)
        unit_price = _safe_decimal(li.unit_price)
        line_total = _safe_decimal(li.line_total)
        # Deterministic derivation — never invented
        if line_total is None and quantity is not None and unit_price is not None:
            line_total = (quantity * unit_price).quantize(_CENTS)
        elif unit_price is None and line_total is not None and quantity not in (None, Decimal("0")):
            unit_price = (line_total / quantity).quantize(_CENTS)
        elif quantity is None and line_total is not None and unit_price not in (None, Decimal("0")):
            quantity = (line_total / unit_price).quantize(_FOUR_DP)

        if quantity is None or unit_price is None or line_total is None:
            skipped_lines += 1
            logger.warning(
                "Omitting invoice line %r — insufficient data (quantity=%s unit_price=%s line_total=%s)",
                li.description, quantity, unit_price, line_total,
            )
            continue
        li.line_total = line_total
        li.quantity = quantity
        li.unit_price = unit_price
        inv.line_items.append(InvoiceLine(
            description=li.description,
            sku=li.sku,
            quantity=quantity,
            unit=li.unit,
            unit_price=unit_price,
            line_total=line_total,
        ))
    if skipped_lines:
        extraction.warnings.append(
            f"{skipped_lines} line item(s) omitted: quantity/price/total could not be determined"
        )
    db.commit()


def _stage_vendor_matching(
    run_id: str, db: Session, extraction: InvoiceExtraction, inv: Invoice,
) -> VendorMatchResult | None:
    """Stage 4 — vendor matching (Phase 4 service). Non-fatal on error."""
    _event(run_id, db, STAGE_VENDOR_MATCHING, RunEventStatus.RUNNING,
           f"Matching vendor: {extraction.vendor_name or 'unknown'}")
    try:
        vendor_result = match_vendor(
            vendor_name=extraction.vendor_name,
            vendor_tax_id=extraction.vendor_tax_id,
        )
        inv.vendor_id = vendor_result.matched_vendor.id if vendor_result.matched_vendor else None
        db.commit()
        _event(run_id, db, STAGE_VENDOR_MATCHING, RunEventStatus.COMPLETED,
               f"Vendor match: {vendor_result.status} — {vendor_result.explanation}",
               {"match_method": vendor_result.match_method,
                "confidence": vendor_result.confidence,
                "status": vendor_result.status})
        return vendor_result
    except Exception as exc:
        db.rollback()
        logger.warning("Vendor matching failed: %s", exc)
        _event(run_id, db, STAGE_VENDOR_MATCHING, RunEventStatus.FAILED,
               f"Vendor matching could not be completed: {exc}")
        return None


def _stage_po_matching(
    run_id: str, db: Session, extraction: InvoiceExtraction,
    matched_vendor_id: Optional[int], inv: Invoice,
) -> POMatchResult | None:
    """Stage 5 — PO matching (Phase 4 service). Non-fatal on error."""
    _event(run_id, db, STAGE_PO_MATCHING, RunEventStatus.RUNNING,
           f"Matching PO: {extraction.po_reference or 'no reference on invoice'}")
    try:
        po_result = match_po(
            po_reference=extraction.po_reference,
            matched_vendor_id=matched_vendor_id,
        )
        inv.purchase_order_id = po_result.matched_po.id if po_result.matched_po else None
        db.commit()
        _event(run_id, db, STAGE_PO_MATCHING, RunEventStatus.COMPLETED,
               f"PO match: {po_result.status} — {po_result.explanation}",
               {"match_method": po_result.match_method, "status": po_result.status})
        return po_result
    except Exception as exc:
        db.rollback()
        logger.warning("PO matching failed: %s", exc)
        _event(run_id, db, STAGE_PO_MATCHING, RunEventStatus.FAILED,
               f"PO matching could not be completed: {exc}")
        return None


def _stage_duplicate_check(
    run_id: str, db: Session, pdf_path: Path, invoice_id: int,
    extraction: InvoiceExtraction, matched_vendor_id: Optional[int],
) -> DuplicateResult | None:
    """Stage 6 — duplicate detection; the current invoice is ALWAYS excluded."""
    _event(run_id, db, STAGE_DUPLICATE_CHECK, RunEventStatus.RUNNING,
           "Checking for duplicates against previous submissions")
    try:
        dup_result = detect_duplicates(
            file_path=pdf_path,
            vendor_id=matched_vendor_id,
            invoice_number=extraction.invoice_number,
            total_amount=_safe_decimal(extraction.total_amount),
            currency=extraction.currency,
            exclude_invoice_id=invoice_id,  # never self-match
        )
        detail = {"status": dup_result.status, "existing_invoice_id": dup_result.existing_invoice_id}
        _event(run_id, db, STAGE_DUPLICATE_CHECK, RunEventStatus.COMPLETED,
               f"Duplicate check: {dup_result.status} — {dup_result.explanation}", detail)
        return dup_result
    except Exception as exc:
        db.rollback()
        logger.warning("Duplicate detection failed: %s", exc)
        _event(run_id, db, STAGE_DUPLICATE_CHECK, RunEventStatus.FAILED,
               f"Duplicate detection could not be completed: {exc}")
        return None


def _stage_amount_validation(
    run_id: str, db: Session, invoice_id: int, extraction: InvoiceExtraction,
    matched_po_id: Optional[int],
) -> AmountValidationResult | None:
    """Stage 7 — amount/PO-balance validation; provisional balances are surfaced."""
    _event(run_id, db, STAGE_AMOUNT_VALIDATION, RunEventStatus.RUNNING,
           "Validating amount against remaining PO balance")
    try:
        amount_result = validate_amount(
            invoice_total=_safe_decimal(extraction.total_amount),
            po_id=matched_po_id,
            currency=extraction.currency,
            exclude_invoice_id=invoice_id,  # current invoice not counted twice
        )
        _event(run_id, db, STAGE_AMOUNT_VALIDATION, RunEventStatus.COMPLETED,
               f"Amount validation: {amount_result.status} — {amount_result.explanation}",
               {"status": amount_result.status,
                "previously_approved_invoiced": amount_result.previously_approved_invoiced,
                "remaining_po_balance": amount_result.remaining_po_balance,
                "metadata": amount_result.metadata})
        return amount_result
    except Exception as exc:
        db.rollback()
        logger.warning("Amount validation failed: %s", exc)
        _event(run_id, db, STAGE_AMOUNT_VALIDATION, RunEventStatus.FAILED,
               f"Amount validation could not be completed: {exc}")
        return None


def _stage_line_item_validation(
    run_id: str, db: Session, invoice_id: int, matched_po_id: Optional[int],
) -> LineItemValidationResult | None:
    """Stage 8 — line-item comparison vs the matched PO (uses persisted lines)."""
    _event(run_id, db, STAGE_LINE_ITEM_VALIDATION, RunEventStatus.RUNNING,
           "Validating line items against the PO")
    try:
        result = validate_line_items(invoice_id=invoice_id, po_id=matched_po_id)
        _event(run_id, db, STAGE_LINE_ITEM_VALIDATION, RunEventStatus.COMPLETED,
               f"Line-item validation: {result.status} — {result.explanation}",
               {"status": result.status,
                "matched": len(result.matched_items),
                "unmatched_invoice": len(result.unmatched_invoice_items),
                "unmatched_po": len(result.unmatched_po_items)})
        return result
    except Exception as exc:
        db.rollback()
        logger.warning("Line-item validation failed: %s", exc)
        _event(run_id, db, STAGE_LINE_ITEM_VALIDATION, RunEventStatus.FAILED,
               f"Line-item validation could not be completed: {exc}")
        return None


def _stage_tax_validation(
    run_id: str, db: Session, inv: Invoice,
) -> TaxValidationResult | None:
    """Stage 9 — tax/arithmetic reconciliation (Decimal, Phase 4 service)."""
    _event(run_id, db, STAGE_TAX_VALIDATION, RunEventStatus.RUNNING,
           "Validating tax arithmetic")
    try:
        tax_result = validate_tax_arithmetic(
            subtotal=inv.subtotal,
            tax_amount=inv.tax_amount,
            discount_amount=inv.discount_amount if inv.discount_amount is not None else Decimal("0"),
            total_amount=inv.total_amount,
        )
        _event(run_id, db, STAGE_TAX_VALIDATION, RunEventStatus.COMPLETED,
               f"Tax validation: {tax_result.status} — {tax_result.explanation}",
               {"status": tax_result.status})
        return tax_result
    except Exception as exc:
        db.rollback()
        logger.warning("Tax validation failed: %s", exc)
        _event(run_id, db, STAGE_TAX_VALIDATION, RunEventStatus.FAILED,
               f"Tax validation could not be completed: {exc}")
        return None


def _stage_decision(
    run_id: str, db: Session, invoice_id: int, extraction: InvoiceExtraction,
    vendor_result, po_result, dup_result, amount_result,
    line_item_result, tax_result, pdf_metadata: ExtractionMetadata,
) -> DecisionResult:
    """Stage 10 — deterministic decision via decide() (Phase 5 engine, no LLM)."""
    _event(run_id, db, STAGE_DECISION, RunEventStatus.RUNNING,
           "Evaluating deterministic decision rules")

    vendor_blocked: Optional[bool] = None
    vendor_inactive: Optional[bool] = None
    if vendor_result and vendor_result.matched_vendor:
        vend = db.get(Vendor, vendor_result.matched_vendor.id)
        if vend is not None:
            vendor_blocked = vend.status.value == "BLOCKED"
            vendor_inactive = vend.status.value == "INACTIVE"

    po_status: Optional[str] = None
    po_belongs_to_vendor: Optional[bool] = None
    po_currency: Optional[str] = None
    if po_result and po_result.matched_po:
        po_obj = db.get(PurchaseOrder, po_result.matched_po.id)
        if po_obj is not None:
            po_status = po_obj.status.value
            po_currency = po_obj.currency
            po_belongs_to_vendor = (po_obj.vendor_id == (vendor_result.matched_vendor.id
                                                         if vendor_result and vendor_result.matched_vendor
                                                         else None))

    currency_mismatch = False
    if amount_result is not None:
        if (amount_result.evidence or {}).get("currency_mismatch"):
            currency_mismatch = True
        elif amount_result.metadata.get("currency_mismatch"):
            currency_mismatch = True
        elif amount_result.status == "WARNING" and "Currency mismatch" in (amount_result.explanation or ""):
            currency_mismatch = True

    # Any stage that failed or returned UNKNOWN must be surfaced, never
    # silently treated as PASS.
    unknown_checks = []
    if vendor_result is None:
        unknown_checks.append("VENDOR_MATCHING")
    if po_result is None:
        unknown_checks.append("PO_MATCHING")
    if dup_result is None:
        unknown_checks.append("DUPLICATE_CHECK")
    if amount_result is None or amount_result.status == "UNKNOWN":
        unknown_checks.append("AMOUNT_VALIDATION")
    if line_item_result is None:
        unknown_checks.append("LINE_ITEM_VALIDATION")
    if tax_result is None:
        unknown_checks.append("TAX_VALIDATION")

    input_data = DecisionInput(
        invoice_number=extraction.invoice_number,
        vendor_name=extraction.vendor_name,
        vendor_tax_id=extraction.vendor_tax_id,
        vendor_match_status=vendor_result.status if vendor_result else None,
        vendor_match_method=vendor_result.match_method if vendor_result else None,
        vendor_confidence=vendor_result.confidence if vendor_result else None,
        vendor_blocked=vendor_blocked,
        vendor_inactive=vendor_inactive,
        vendor_candidates=vendor_result.candidates if vendor_result else [],
        po_reference=extraction.po_reference,
        po_match_status=po_result.status if po_result else None,
        po_match_method=po_result.match_method if po_result else None,
        po_confidence=po_result.confidence if po_result else None,
        po_status=po_status,
        po_belongs_to_vendor=po_belongs_to_vendor,
        po_candidates=po_result.candidates if po_result else [],
        duplicate_status=dup_result.status if dup_result else None,
        duplicate_evidence=dup_result.evidence if dup_result else None,
        amount_validation_status=amount_result.status if amount_result else None,
        invoice_amount=str(extraction.total_amount) if extraction.total_amount is not None else None,
        po_total=amount_result.po_total if amount_result else None,
        remaining_po_balance=amount_result.remaining_po_balance if amount_result else None,
        previously_approved_invoiced=(
            amount_result.previously_approved_invoiced if amount_result else "0.00"
        ),
        amount_explanation=amount_result.explanation if amount_result else None,
        invoice_currency=extraction.currency,
        po_currency=po_currency,
        currency_mismatch=currency_mismatch,
        tax_validation_status=tax_result.status if tax_result else None,
        tax_explanation=tax_result.explanation if tax_result else None,
        line_item_validation_status=line_item_result.status if line_item_result else None,
        line_item_explanation=line_item_result.explanation if line_item_result else None,
        missing_critical_fields=_missing_critical_fields(extraction),
        extraction_status=extraction.extraction_status,
        min_extraction_confidence=_min_extraction_confidence(extraction),
        extraction_warnings=list(extraction.warnings) + list(pdf_metadata.warnings or []),
        unknown_checks=unknown_checks,
    )

    decision_result = decide(input_data, policy=DEFAULT_POLICY)

    _event(run_id, db, STAGE_DECISION, RunEventStatus.COMPLETED,
           f"Decision: {decision_result.decision} — {decision_result.summary}",
           {"decision": decision_result.decision, "policy_version": decision_result.policy_version})
    return decision_result


def _stage_persistence(
    run_id: str, db: Session, inv: Invoice, settings,
    extraction: InvoiceExtraction, pdf_metadata: ExtractionMetadata,
    vendor_result, po_result, dup_result, amount_result,
    line_item_result, tax_result, decision_result: DecisionResult,
):
    """Stage 11 — persist every output required to reconstruct the run."""
    _event(run_id, db, STAGE_PERSISTENCE, RunEventStatus.RUNNING,
           "Persisting decision and supporting evidence")

    run = db.get(ProcessingRun, run_id)
    if run is None:
        raise RuntimeError("processing run disappeared before result persistence")

    run.status = ProcessingRunStatus.COMPLETED
    run.decision = decision_result.decision  # business decision only
    run.completed_at = _now()
    run.llm_provider = settings.llm_provider
    run.llm_model = settings.llm_model
    run.extraction_json = _dumps(extraction.to_json_safe())
    run.document_meta_json = _dumps(pdf_metadata.model_dump())
    run.vendor_match_json = _dumps(vendor_result.model_dump()) if vendor_result else None
    run.po_match_json = _dumps(po_result.model_dump()) if po_result else None
    run.duplicate_check_json = _dumps(dup_result.model_dump()) if dup_result else None
    run.amount_validation_json = _dumps(amount_result.model_dump()) if amount_result else None
    run.line_item_validation_json = _dumps(line_item_result.model_dump()) if line_item_result else None
    run.tax_validation_json = _dumps(tax_result.model_dump()) if tax_result else None
    run.decision_json = _dumps(decision_result.to_json_safe())
    db.commit()

    _event(run_id, db, STAGE_PERSISTENCE, RunEventStatus.COMPLETED,
           "Decision and full evidence persisted",
           {"persisted": ["extraction", "document_meta", "vendor_match", "po_match",
                          "duplicate_check", "amount_validation", "line_item_validation",
                          "tax_validation", "decision"]})

    _event(run_id, db, STAGE_COMPLETED, RunEventStatus.COMPLETED,
           f"Processing complete — decision: {decision_result.decision}",
           {"decision": decision_result.decision})


# ══════════════════════════════════════════════════════════════════════════════
# Worker entry point (FastAPI BackgroundTasks)
# ══════════════════════════════════════════════════════════════════════════════

def _claim_run(run_id: str, db: Session, settings) -> bool:
    """Atomically claim a PENDING run (PENDING → RUNNING).

    Returns False when the run is missing, already claimed or already finished,
    which prevents concurrent double-processing and double-counting.
    """
    from sqlalchemy import update
    now = _now()
    res = db.execute(
        update(ProcessingRun)
        .where(ProcessingRun.id == run_id, ProcessingRun.status == ProcessingRunStatus.PENDING)
        .values(
            status=ProcessingRunStatus.RUNNING,
            started_at=now,
            llm_provider=settings.llm_provider,
            llm_model=settings.llm_model,
        )
    )
    db.commit()
    return res.rowcount == 1


def _run_workflow(run_id: str, invoice_id: int) -> tuple[str, Optional[str]]:
    """Execute the full processing workflow for one run.

    Returns (final_status, final_decision); final_decision is None for a
    technical failure — business decisions (APPROVE/REVIEW/REJECT) are only
    produced by successfully finished runs.
    """
    settings = get_settings()
    db = SessionLocal()
    try:
        try:
            claimed = _claim_run(run_id, db, settings)
        except Exception as exc:
            logger.error("Could not claim run %s: %s", run_id, exc)
            # Do not leave the run stuck PENDING — a technical failure is FAILED
            _fail_run(run_id, db, STAGE_RECEIVED,
                      f"Could not claim the run for processing: {exc}")
            return "FAILED", None
        if not claimed:
            logger.warning("Run %s is not PENDING — skipping (already claimed or finished)", run_id)
            return "SKIPPED", None

        inv = db.get(Invoice, invoice_id)
        if inv is None:
            _fail_run(run_id, db, "RECEIVED", f"Invoice {invoice_id} not found")
            return "FAILED", None

        _event(run_id, db, STAGE_RECEIVED, RunEventStatus.COMPLETED,
               f"Processing started for invoice {inv.id} ({inv.storage_path.rsplit('/', 1)[-1]})")

        pdf_path = Path(inv.storage_path) if inv.storage_path else None
        if not pdf_path or not pdf_path.exists():
            _fail_run(run_id, db, STAGE_DOCUMENT_PROCESSING,
                      f"Stored PDF missing at {pdf_path}",
                      {"document_meta": None})
            return "FAILED", None

        # ── 1. Document processing (PDF text extraction) ────────────────────
        try:
            metadata, full_text = _stage_document_processing(run_id, db, pdf_path)
        except Exception as exc:
            logger.error("Document processing failed for run %s: %s", run_id, exc)
            _fail_run(run_id, db, STAGE_DOCUMENT_PROCESSING, f"PDF extraction failed: {exc}",
                      {"error": str(exc)})
            return "FAILED", None

        # ── 2. OCR fallback (when applicable) ───────────────────────────────
        try:
            full_text = _stage_ocr(run_id, db, pdf_path, metadata, full_text)
        except Exception as exc:
            logger.error("OCR failed for run %s: %s", run_id, exc)
            _fail_run(run_id, db, STAGE_OCR_PROCESSING,
                      f"OCR failed and no digital text available: {exc}",
                      {"document_meta": metadata.model_dump()})
            return "FAILED", None

        # ── 3. LLM structured extraction ────────────────────────────────────
        try:
            extraction = _stage_llm_extraction(run_id, db, full_text, metadata)
        except Exception as exc:
            logger.error("LLM extraction failed for run %s: %s", run_id, exc)
            _fail_run(run_id, db, STAGE_LLM_EXTRACTION, f"LLM extraction failed: {exc}",
                      {"error": str(exc), "document_meta": metadata.model_dump()})
            return "FAILED", None

        if extraction.extraction_status == "FAILED":
            # Technical failure → keep the failure honest, never a business REVIEW.
            _persist_extraction(db, inv, extraction)  # persist whatever partial data survived
            run = db.get(ProcessingRun, run_id)
            run.extraction_json = _dumps(extraction.to_json_safe())
            run.document_meta_json = _dumps(metadata.model_dump())
            _fail_run(run_id, db, STAGE_LLM_EXTRACTION,
                      "LLM extraction failed: " + "; ".join(extraction.warnings[:3]),
                      {"extraction_status": extraction.extraction_status})
            return "FAILED", None

        # ── Persist extraction onto the invoice (retry-safe) ────────────────
        try:
            _persist_extraction(db, inv, extraction)
        except Exception as exc:
            db.rollback()
            logger.error("Extraction persistence failed for run %s: %s", run_id, exc)
            _fail_run(run_id, db, STAGE_LLM_EXTRACTION,
                      f"Could not persist extracted data: {exc}",
                      {"error": str(exc), "document_meta": metadata.model_dump()})
            return "FAILED", None

        # ── 4–9. Matching, duplicates and validations (each non-fatal) ──────
        vendor_result = _stage_vendor_matching(run_id, db, extraction, inv)
        matched_vendor_id = (
            vendor_result.matched_vendor.id if vendor_result and vendor_result.matched_vendor else None
        )
        po_result = _stage_po_matching(run_id, db, extraction, matched_vendor_id, inv)
        matched_po_id = po_result.matched_po.id if po_result and po_result.matched_po else None
        dup_result = _stage_duplicate_check(run_id, db, pdf_path, inv.id, extraction, matched_vendor_id)
        amount_result = _stage_amount_validation(run_id, db, inv.id, extraction, matched_po_id)
        line_item_result = _stage_line_item_validation(run_id, db, inv.id, matched_po_id)
        tax_result = _stage_tax_validation(run_id, db, inv)

        # ── 10. Deterministic decision ──────────────────────────────────────
        try:
            decision_result = _stage_decision(
                run_id, db, inv.id, extraction, vendor_result, po_result, dup_result,
                amount_result, line_item_result, tax_result, metadata,
            )
        except Exception as exc:
            logger.error("Decision engine failed for run %s: %s", run_id, exc)
            _fail_run(run_id, db, STAGE_DECISION, f"Decision evaluation failed: {exc}",
                      {"error": str(exc)})
            return "FAILED", None

        # ── 11. Persist result + complete ───────────────────────────────────
        try:
            _stage_persistence(
                run_id, db, inv, settings, extraction, metadata, vendor_result,
                po_result, dup_result, amount_result, line_item_result,
                tax_result, decision_result,
            )
        except Exception as exc:
            logger.error("Result persistence failed for run %s: %s", run_id, exc)
            _fail_run(run_id, db, STAGE_PERSISTENCE,
                      f"Result persistence failed: {exc}", {"error": str(exc)})
            return "FAILED", None

        return "COMPLETED", decision_result.decision

    except Exception as exc:
        # Last-resort catch-all: preserve history, mark FAILED, never fake completion.
        logger.exception("Unhandled workflow error for run %s", run_id)
        _fail_run(run_id, db, "WORKFLOW", f"Unexpected workflow error: {exc}")
        return "FAILED", None
    finally:
        db.close()


def process_invoice_background(run_id: str, invoice_id: int, settings=None) -> None:
    """Background task entry point (single-instance demo).

    Creates a fresh SQLAlchemy session inside the worker — request-scoped
    sessions are never passed across threads.
    """
    status, decision = _run_workflow(run_id, invoice_id)
    logger.info("Workflow finished for run %s: status=%s decision=%s", run_id, status, decision)


def retry_failed_run(run_id: str) -> bool:
    """Reset a FAILED run to PENDING so it can be claimed again (manual retry).

    Prior events and any partial JSON are retained; the workflow rewrites the
    run's results on success. Returns False when the run is missing or not in
    FAILED state. Uses an atomic UPDATE so concurrent retries cannot double-claim.
    """
    from sqlalchemy import update
    db = SessionLocal()
    try:
        res = db.execute(
            update(ProcessingRun)
            .where(ProcessingRun.id == run_id, ProcessingRun.status == ProcessingRunStatus.FAILED)
            .values(status=ProcessingRunStatus.PENDING, error_message=None,
                    completed_at=None, decision=None)
        )
        db.commit()
        if res.rowcount == 1:
            _event(run_id, db, STAGE_RECEIVED, RunEventStatus.COMPLETED,
                   "Run reset to PENDING after failure — retry requested")
            return True
        return False
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
