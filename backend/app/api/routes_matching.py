"""Diagnostic matching and validation endpoint — Phase 4."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
import logging

from app.db.session import SessionLocal, init_db
from app.db.seed import seed as run_seed
from app.schemas.invoice import InvoiceExtraction
from app.schemas.matching import MatchingAndValidationResult
from app.services.vendor_matcher import match_vendor
from app.services.po_matcher import match_po
from app.services.duplicate_detector import detect_duplicates
from app.services.amount_validator import validate_amount
from app.services.line_item_validator import validate_line_items
from app.services.tax_validator import validate_tax_arithmetic

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/diagnostic", tags=["diagnostic"])


class MatchingInput(BaseModel):
    """Structured invoice input for the matching/validation diagnostic endpoint."""
    # Vendor fields
    vendor_name: Optional[str] = Field(default=None, description="Vendor name from invoice")
    vendor_tax_id: Optional[str] = Field(default=None, description="Tax ID from invoice")

    # Invoice identifier
    invoice_number: Optional[str] = Field(default=None, description="Invoice number")

    # PO fields
    po_reference: Optional[str] = Field(default=None, description="PO reference from invoice")

    # Financial fields
    currency: Optional[str] = Field(default=None, description="ISO 4217 currency code")
    subtotal: Optional[float] = Field(default=None, description="Subtotal before tax/discount")
    tax_amount: Optional[float] = Field(default=None, description="Total tax amount")
    discount_amount: Optional[float] = Field(default=None, description="Total discount amount")
    total_amount: Optional[float] = Field(default=None, description="Grand total")

    # Line items
    line_items: List[dict] = Field(default_factory=list)


class MatchingDiagnosticResponse(BaseModel):
    result: MatchingAndValidationResult
    notes: List[str] = Field(default_factory=list)


@router.post("/match-validate", response_model=MatchingDiagnosticResponse)
async def diagnostic_match_validate(input_data: MatchingInput):
    """Run vendor matching, PO matching, duplicate detection, amount validation,
    line-item validation, and tax arithmetic validation against the procurement DB.

    Does NOT persist results as actual processing runs. Use for inspection only.
    Requires a seeded database — seeds automatically if empty.
    """
    # Ensure DB is initialized and has seed data
    init_db()
    db = SessionLocal()
    try:
        vendor_count = db.query(db.bind.execute).first()  # placeholder; real check below
        from sqlalchemy import text
        cnt = db.execute(text("SELECT COUNT(*) FROM vendors")).scalar()
        if not isinstance(cnt, int) or cnt == 0:
            run_seed()
    finally:
        db.close()

    db = SessionLocal()
    try:
        notes: List[str] = []

        # 1. Vendor matching
        vendor_result = match_vendor(
            vendor_name=input_data.vendor_name,
            vendor_tax_id=input_data.vendor_tax_id,
        )
        if vendor_result.status in ("BLOCKED_INACTIVE", "NEEDS_REVIEW"):
            notes.append(f"Vendor result needs review: {vendor_result.explanation}")

        matched_vendor_id = (
            vendor_result.matched_vendor.id
            if vendor_result.matched_vendor else None
        )

        # 2. PO matching
        po_result = match_po(
            po_reference=input_data.po_reference,
            matched_vendor_id=matched_vendor_id,
        )
        if po_result.status in ("AMBIGUOUS", "MISSING_PO"):
            notes.append(f"PO result needs review: {po_result.explanation}")

        matched_po_id = (
            po_result.matched_po.id
            if po_result.matched_po else None
        )

        # 3. Duplicate detection
        dup_result = detect_duplicates(
            vendor_id=matched_vendor_id,
            invoice_number=input_data.invoice_number,
            total_amount=None,  # not needed for non-document duplicates in this diag path
            currency=input_data.currency,
        )
        if dup_result.status != "NO_DUPLICATE_FOUND":
            notes.append(f"Duplicate signal: {dup_result.status} — {dup_result.explanation}")

        # 4. Amount validation
        from decimal import Decimal
        inv_total = Decimal(str(input_data.total_amount)) if input_data.total_amount is not None else Decimal("0")
        amount_result = validate_amount(
            invoice_total=inv_total,
            po_id=matched_po_id,
            currency=input_data.currency,
        )

        # 5. Tax / arithmetic validation
        tax_result = validate_tax_arithmetic(
            subtotal=input_data.subtotal,
            tax_amount=input_data.tax_amount,
            discount_amount=input_data.discount_amount or 0,
            total_amount=input_data.total_amount,
        )

        # 6. Line-item validation (requires an invoice_id in the DB)
        # For diagnostic purposes we create a temporary Invoice row to hold the lines,
        # then run line-item comparison against the matched PO.
        from app.db.models import Invoice as DBInvoice, InvoiceLine
        temp_inv = None
        if matched_po_id and input_data.line_items:
            temp_inv = DBInvoice(
                invoice_number=input_data.invoice_number,
                vendor_id=matched_vendor_id,
                purchase_order_id=matched_po_id,
                currency=input_data.currency,
                subtotal=Decimal(str(input_data.subtotal or 0)),
                tax_amount=Decimal(str(input_data.tax_amount or 0)),
                discount_amount=Decimal(str(input_data.discount_amount or 0)),
                total_amount=inv_total,
            )
            db.add(temp_inv)
            db.flush()

            for li in input_data.line_items:
                from decimal import Decimal as D
                line = InvoiceLine(
                    invoice_id=temp_inv.id,
                    description=li.get("description", ""),
                    sku=li.get("sku"),
                    quantity=D(str(li["quantity"])) if "quantity" in li else D("0"),
                    unit=li.get("unit"),
                    unit_price=D(str(li["unit_price"])) if "unit_price" in li else D("0"),
                    line_total=D(str(li["line_total"])) if "line_total" in li else D("0"),
                )
                db.add(line)
            db.commit()

        line_result = validate_line_items(
            invoice_id=temp_inv.id if temp_inv else 0,
            po_id=matched_po_id,
        )
        if temp_inv:
            db.delete(temp_inv)
            for line in temp_inv.line_items:
                db.delete(line)
            db.commit()

        overall = MatchingAndValidationResult(
            vendor_match=vendor_result,
            po_match=po_result,
            duplicate_check=dup_result,
            amount_validation=amount_result,
            line_item_validation=line_result,
            tax_validation=tax_result,
            warnings=notes,
        )

        return MatchingDiagnosticResponse(result=overall)
    except Exception as e:
        logger.exception("Matching diagnostic failed")
        raise HTTPException(status_code=500, detail=f"Matching validation error: {e}")
    finally:
        db.close()


@router.get("/match-validate/health")
async def match_validate_health():
    """Check that the matching/validation services are importable and DB is seeded."""
    from sqlalchemy import text
    init_db()
    db = SessionLocal()
    try:
        cnt = db.execute(text("SELECT COUNT(*) FROM vendors")).scalar()
        vendor_count = int(cnt) if cnt else 0
        po_count = int(db.execute(text("SELECT COUNT(*) FROM purchase_orders")).scalar())
        return {
            "status": "ok",
            "vendors_in_db": vendor_count,
            "purchase_orders_in_db": po_count,
            "services_available": [
                "vendor_matcher",
                "po_matcher",
                "duplicate_detector",
                "amount_validator",
                "line_item_validator",
                "tax_validator",
            ],
        }
    finally:
        db.close()
