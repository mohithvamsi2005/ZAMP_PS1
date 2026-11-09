"""Pydantic schemas for matching and validation results."""
from decimal import Decimal, InvalidOperation
from typing import Optional, List, Any

from pydantic import BaseModel, Field


# ── Common result fields ──────────────────────────────────────────────────────


class CheckResult(BaseModel):
    """Single check output with explainable evidence."""
    check_name: str = Field(description="Human-readable name of the check")
    status: str = Field(
        description="PASS | FAIL | WARNING | UNKNOWN | NEEDS_REVIEW "
                    "| MATCHED | UNMATCHED | AMBIGUOUS | MISSING_PO "
                    "| EXACT_DOCUMENT_DUPLICATE | EXACT_INVOICE_DUPLICATE | POTENTIAL_DUPLICATE | NO_DUPLICATE_FOUND"
    )
    expected_value: Optional[Any] = None
    actual_value: Optional[Any] = None
    difference: Optional[Any] = None
    explanation: Optional[str] = None
    evidence: Optional[dict] = Field(default=None, description="Supporting data")
    metadata: dict = Field(default_factory=dict)


# ── Vendor match result ───────────────────────────────────────────────────────


class MatchedVendor(BaseModel):
    id: int
    vendor_code: str
    legal_name: str

    @classmethod
    def from_vendor_model(cls, vendor) -> "MatchedVendor":
        return cls(
            id=vendor.id,
            vendor_code=vendor.vendor_code,
            legal_name=vendor.legal_name,
        )


class VendorMatchResult(CheckResult):
    """Full vendor matching output."""
    status: str  # MATCHED | UNMATCHED | AMBIGUOUS | NEEDS_REVIEW
    matched_vendor: Optional[MatchedVendor] = None
    match_method: str = Field(
        description="EXACT_TAX_ID | EXACT_NAME | FUZZY_NAME"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Matching score — not a probability of correctness",
    )
    candidates: List[dict] = Field(
        default_factory=list,
        description="Other plausible vendor matches when ambiguous",
    )


# ── PO match result ───────────────────────────────────────────────────────────


class MatchedPO(BaseModel):
    id: int
    po_number: str
    total_amount: str  # Decimal as string for JSON safety
    currency: str

    @classmethod
    def from_po_model(cls, po) -> "MatchedPO":
        return cls(
            id=po.id,
            po_number=po.po_number,
            total_amount=str(po.total_amount),
            currency=po.currency,
        )


class POMatchResult(CheckResult):
    """Full PO matching output."""
    status: str  # MATCHED | UNMATCHED | AMBIGUOUS | MISSING_PO
    matched_po: Optional[MatchedPO] = None
    match_method: str = Field(
        description="EXACT_PO_NUMBER | NORMALIZED_PO | CANDIDATE_VENDOR"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    candidates: List[dict] = Field(default_factory=list)


# ── Duplicate check result ────────────────────────────────────────────────────


class DuplicateResult(CheckResult):
    """Duplicate detection output."""
    status: str  # EXACT_DOCUMENT_DUPLICATE | EXACT_INVOICE_DUPLICATE | POTENTIAL_DUPLICATE | NO_DUPLICATE_FOUND
    existing_invoice_id: Optional[int] = None
    evidence: Optional[dict] = None


# ── Amount validation result ──────────────────────────────────────────────────


class AmountValidationResult(CheckResult):
    """Amount comparison output with PO balance awareness."""
    status: str  # PASS | FAIL | WARNING
    po_total: Optional[str] = None
    previously_approved_invoiced: str = Field(default="0.00")
    remaining_po_balance: Optional[str] = None
    invoice_amount: str
    tolerance_absolute: str
    tolerance_percent: float


# ── Line-item validation result ───────────────────────────────────────────────


class LineItemMatch(BaseModel):
    """A single matched or mismatched line item."""
    invoice_line_index: int
    po_line_index: Optional[int] = None
    status: str  # MATCHED | QUANTITY_MISMATCH | UNIT_PRICE_MISMATCH | LINE_TOTAL_MISMATCH | MISSING_IN_PO | UNEXPECTED_INVOICE
    description_match: str  # EXACT_SKU | NORMALIZED_DESC | FUZZY_DESC
    invoice_description: Optional[str] = None
    po_description: Optional[str] = None
    invoice_quantity: Optional[Decimal] = None
    po_quantity: Optional[Decimal] = None
    invoice_unit_price: Optional[Decimal] = None
    po_unit_price: Optional[Decimal] = None
    invoice_line_total: Optional[Decimal] = None
    po_line_total: Optional[Decimal] = None
    difference: Optional[Any] = None
    explanation: Optional[str] = None


class LineItemValidationResult(CheckResult):
    """Line-item comparison output."""
    status: str  # PASS | FAIL | WARNING
    matched_items: List[LineItemMatch] = Field(default_factory=list)
    unmatched_invoice_items: List[dict] = Field(default_factory=list)
    unmatched_po_items: List[dict] = Field(default_factory=list)


# ── Tax / arithmetic validation result ────────────────────────────────────────


class TaxValidationResult(CheckResult):
    """Invoice subtotal + tax − discount reconciliation."""
    status: str  # PASS | FAIL | UNKNOWN
    subtotal: Optional[str] = None
    tax_amount: Optional[str] = None
    discount_amount: str = "0.00"
    expected_total: Optional[str] = None
    actual_total: Optional[str] = None
    difference: Optional[str] = None


# ── Overall validation summary ────────────────────────────────────────────────


class MatchingAndValidationResult(BaseModel):
    """Top-level result returned by the diagnostic matching endpoint."""
    vendor_match: VendorMatchResult
    po_match: POMatchResult
    duplicate_check: DuplicateResult
    amount_validation: AmountValidationResult
    line_item_validation: LineItemValidationResult
    tax_validation: TaxValidationResult
    warnings: List[str] = Field(default_factory=list)
