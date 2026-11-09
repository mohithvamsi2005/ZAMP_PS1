"""Pydantic schemas for the deterministic decision engine output."""
from typing import Optional, List, Any

from pydantic import BaseModel, Field


class RuleEvaluation(BaseModel):
    """A single rule evaluation with explanation and evidence."""
    rule_id: str = Field(description="Stable unique identifier for this rule (e.g. VENDOR_001)")
    rule_name: str = Field(description="Human-readable name of the rule")
    status: str = Field(
        description="PASS | FAIL | WARNING | INFO"
    )
    severity: str = Field(
        description="INFO | REVIEW | REJECT",
    )
    explanation: str = Field(description="Plain-language reason for this rule's outcome")
    evidence: dict = Field(
        default_factory=dict,
        description="Structured data supporting the decision (expected/actual values, scores, etc.)",
    )


class DecisionResult(BaseModel):
    """Final deterministic decision output."""
    decision: str = Field(
        description="APPROVE | REVIEW | REJECT — the final outcome"
    )
    policy_version: str = Field(
        default="1.0",
        description="Version of the decision policy used",
    )
    summary: str = Field(
        description="Plain-language one-line summary understandable to an AP employee"
    )
    rules_evaluated: List[RuleEvaluation] = Field(
        description="All rules that were evaluated, in priority order"
    )
    hard_failures: List[str] = Field(
        default_factory=list,
        description="Rules that trigger automatic REJECT",
    )
    review_reasons: List[str] = Field(
        default_factory=list,
        description="Conditions requiring human review",
    )
    approval_eligible: bool = Field(
        description="True only when all mandatory conditions are satisfied"
    )

    def to_json_safe(self) -> dict:
        """Return a JSON-serialisable representation."""
        return self.model_dump()


class DecisionInput(BaseModel):
    """Structured input that the decision engine accepts — mirrors Phase 4 output."""
    # Invoice identifier
    invoice_number: Optional[str] = Field(default=None, description="Invoice number from document")

    # Vendor matching result
    vendor_name: Optional[str] = Field(default=None, description="Vendor name from invoice")
    vendor_tax_id: Optional[str] = Field(default=None, description="Tax ID from invoice")
    vendor_match_status: Optional[str] = Field(
        default=None,
        description="MATCHED | UNMATCHED | AMBIGUOUS | NEEDS_REVIEW",
    )
    vendor_match_method: Optional[str] = Field(default=None)
    vendor_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    vendor_blocked: Optional[bool] = Field(default=None, description="Whether matched vendor is BLOCKED")
    vendor_inactive: Optional[bool] = Field(default=None, description="Whether matched vendor is INACTIVE")
    vendor_candidates: List[dict] = Field(
        default_factory=list,
        description="Other plausible vendor matches when ambiguous",
    )

    # PO matching result
    po_reference: Optional[str] = Field(default=None)
    po_match_status: Optional[str] = Field(
        default=None,
        description="MATCHED | UNMATCHED | AMBIGUOUS | MISSING_PO",
    )
    po_match_method: Optional[str] = Field(default=None)
    po_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    po_status: Optional[str] = Field(
        default=None,
        description="OPEN | CLOSED | CANCELLED — from DB when matched",
    )
    po_belongs_to_vendor: Optional[bool] = Field(
        default=None,
        description="Whether PO belongs to the matched vendor (false = cross-vendor)",
    )
    po_candidates: List[dict] = Field(default_factory=list)

    # Duplicate detection result
    duplicate_status: Optional[str] = Field(
        default=None,
        description="NO_DUPLICATE_FOUND | EXACT_DOCUMENT_DUPLICATE | EXACT_INVOICE_DUPLICATE | POTENTIAL_DUPLICATE",
    )
    duplicate_evidence: Optional[dict] = None

    # Amount validation result
    amount_validation_status: Optional[str] = Field(
        default=None,
        description="PASS | FAIL | WARNING",
    )
    invoice_amount: Optional[str] = Field(default=None)
    po_total: Optional[str] = Field(default=None)
    remaining_po_balance: Optional[str] = Field(default=None)
    previously_approved_invoiced: str = Field(default="0.00")
    amount_explanation: Optional[str] = Field(default=None)

    # Currency
    invoice_currency: Optional[str] = Field(default=None)
    po_currency: Optional[str] = Field(default=None)
    currency_mismatch: Optional[bool] = Field(default=None)

    # Tax / arithmetic validation result
    tax_validation_status: Optional[str] = Field(
        default=None,
        description="PASS | FAIL | UNKNOWN",
    )
    tax_explanation: Optional[str] = Field(default=None)

    # Line-item validation result
    line_item_validation_status: Optional[str] = Field(
        default=None,
        description="PASS | FAIL | WARNING",
    )
    line_item_explanation: Optional[str] = Field(default=None)

    # Required fields check (Phase 5 adds this — upstream services don't cover it directly)
    missing_critical_fields: List[str] = Field(
        default_factory=list,
        description="Names of required invoice fields that are null/missing",
    )

    # Extraction evidence
    extraction_status: Optional[str] = Field(
        default=None,
        description="SUCCESS | PARTIAL | FAILED — from LLM extraction stage",
    )
    min_extraction_confidence: Optional[float] = Field(
        default=None,
        ge=0.0, le=1.0,
        description="Minimum confidence among critical fields",
    )
    extraction_warnings: List[str] = Field(default_factory=list)

    # Unknown / unvalidated checks — any check that could not be completed
    unknown_checks: List[str] = Field(
        default_factory=list,
        description="Names of validations that returned UNKNOWN or could not execute",
    )
