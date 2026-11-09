"""Configurable decision policy — central source for all thresholds and rules."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DecisionPolicy:
    """Immutable configuration for the deterministic decision engine.

    All values are explicit demo assumptions; change them to reflect
    real AP policy without touching business logic.
    """
    # Policy version string — bumped when rules or thresholds change
    version: str = "1.0"

    # ── REJECT triggers (hard failures) ────────────────────────────────────────
    reject_on_exact_document_duplicate: bool = True
    reject_on_exact_invoice_duplicate: bool = True
    reject_on_blocked_vendor: bool = True
    # A blocked vendor that appears ONLY as a fuzzy candidate (not the primary match)
    # does NOT trigger automatic rejection — it falls through to REVIEW.

    # ── REVIEW triggers ────────────────────────────────────────────────────────
    review_on_missing_critical_fields: bool = True
    review_on_unmatched_vendor: bool = True
    review_on_ambiguous_vendor: bool = True
    review_on_needs_review_vendor: bool = True       # blocked/inactive vendor as primary match
    review_on_inactive_vendor: bool = True           # inactive vendor (not blocked)
    review_on_missing_po: bool = True
    review_on_ambiguous_po: bool = True
    review_on_unmatched_po: bool = True
    review_on_cancelled_po: bool = True
    review_on_closed_po: bool = True                 # closed PO is not auto-rejected per spec
    review_on_currency_mismatch: bool = True
    review_on_amount_exceeds_balance: bool = True
    review_on_provisional_po_balance: bool = True
    review_on_potential_duplicate: bool = True
    review_on_tax_failure: bool = True
    review_on_tax_unknown: bool = True
    review_on_line_item_discrepancy: bool = True
    review_on_low_extraction_evidence: bool = True
    review_on_unknown_validation: bool = True
    review_on_missing_mandatory_check: bool = True

    # ── Extraction evidence thresholds ─────────────────────────────────────────
    min_extraction_confidence: float = 0.80          # minimum confidence for critical fields
    acceptable_extraction_status: frozenset = field(default_factory=lambda: frozenset({"SUCCESS"}))
    # PARTIAL and FAILED extraction both trigger REVIEW (via low evidence path)

    # ── Approval requirements ──────────────────────────────────────────────────
    require_exact_vendor_match: bool = True          # fuzzy-only vendor → REVIEW, not APPROVE
    require_exact_po_match: bool = True              # fuzzy/candidate PO → REVIEW, not APPROVE
    require_active_vendor: bool = True
    require_open_po: bool = True
    require_reliable_balance: bool = True            # no provisional balance for auto-approve

    # ── Tolerance (mirrors amount_validator defaults) ─────────────────────────
    po_amount_tolerance_percent: float = 1.0
    po_amount_tolerance_absolute: str = "100.00"


DEFAULT_POLICY = DecisionPolicy()
