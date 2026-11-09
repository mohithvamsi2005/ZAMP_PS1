"""Pydantic schemas for invoice extraction output."""
from decimal import Decimal, InvalidOperation
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator


class FieldEvidence(BaseModel):
    """A single extracted field with supporting document evidence."""
    value: Optional[str] = None
    confidence: float = 0.0
    evidence: Optional[str] = None
    page: Optional[int] = None

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        if v < 0.0:
            return 0.0
        if v > 1.0:
            return 1.0
        return round(v, 3)


class LineItem(BaseModel):
    """A single line item from an invoice."""
    description: Optional[str] = None
    sku: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    unit_price: Optional[Decimal] = None
    line_total: Optional[Decimal] = None

    @field_validator("quantity", "unit_price", "line_total")
    @classmethod
    def parse_decimal(cls, v):
        if v is None:
            return None
        try:
            return Decimal(str(v))
        except InvalidOperation:
            return None


class InvoiceExtraction(BaseModel):
    """Structured invoice extraction result from the LLM."""
    # Invoice information
    invoice_number: Optional[str] = Field(default=None, description="Invoice number from document")
    invoice_date: Optional[str] = Field(default=None, description="ISO date (YYYY-MM-DD)")
    due_date: Optional[str] = Field(default=None, description="ISO date (YYYY-MM-DD)")
    currency: Optional[str] = Field(default=None, description="ISO 4217 currency code")
    po_reference: Optional[str] = Field(default=None, description="Purchase order reference")

    # Vendor information
    vendor_name: Optional[str] = Field(default=None, description="Vendor name as printed on invoice")
    vendor_tax_id: Optional[str] = Field(default=None, description="Tax identification number")

    # Financial information
    subtotal: Optional[Decimal] = Field(default=None, description="Subtotal before tax/discount")
    tax_amount: Optional[Decimal] = Field(default=None, description="Total tax amount")
    discount_amount: Optional[Decimal] = Field(default=None, description="Total discount amount")
    total_amount: Optional[Decimal] = Field(default=None, description="Grand total")

    # Line items
    line_items: List[LineItem] = Field(default_factory=list)

    # Extraction metadata
    source_pages: List[int] = Field(default_factory=list, description="Page numbers with extractable text")
    evidence: dict = Field(default_factory=dict, description="Per-field supporting text evidence")
    extraction_status: str = Field(
        default="SUCCESS",
        description="SUCCESS | PARTIAL | FAILED"
    )
    warnings: List[str] = Field(default_factory=list)

    @field_validator("line_items")
    @classmethod
    def validate_line_items(cls, v):
        if isinstance(v, list):
            return [LineItem(**item) if isinstance(item, dict) else item for item in v]
        return []

    def to_json_safe(self) -> dict:
        """Return a JSON-serialisable representation (Decimal → str)."""
        data = self.model_dump()
        for key in ("subtotal", "tax_amount", "discount_amount", "total_amount"):
            val = data.get(key)
            if isinstance(val, Decimal):
                data[key] = str(val)
        for item in data.get("line_items", []):
            for k in ("quantity", "unit_price", "line_total"):
                v = item.get(k)
                if isinstance(v, Decimal):
                    item[k] = str(v)
        return data


class ExtractionMetadata(BaseModel):
    """Document-level processing metadata returned alongside extraction."""
    page_count: int
    pages_processed: List[dict]  # [{"page": N, "method": "PDF_TEXT" | "OCR", "confidence": float}]
    warnings: List[str]
    document_hash: str
    total_chars_extracted: int
    processing_errors: List[str] = Field(default_factory=list)
    source_pages: List[int] = Field(default_factory=list, description="Page numbers with extractable text")
