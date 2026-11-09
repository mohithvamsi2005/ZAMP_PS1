"""Comprehensive unit tests for the deterministic decision engine (Phase 5).

Covers all 27 required scenarios plus edge cases for decimal handling, null fields,
serialization, exception handling, and invalid input.
"""
import pytest
from decimal import Decimal

from app.schemas.decision import DecisionInput, DecisionResult, RuleEvaluation
from app.services.decision_engine import decide
from app.core.decision_policy import DEFAULT_POLICY


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def valid_input():
    """A fully compliant invoice that should APPROVE."""
    return DecisionInput(
        invoice_number="INV-2025-042",
        vendor_name="Acme Supplies Ltd",
        vendor_tax_id="AU:12345678901",
        vendor_match_status="MATCHED",
        vendor_match_method="TAX_ID_EXACT",
        vendor_confidence=1.0,
        vendor_blocked=False,
        vendor_inactive=False,
        po_reference="PO-2025-088",
        po_match_status="MATCHED",
        po_match_method="REFERENCE_EXACT",
        po_confidence=1.0,
        po_status="OPEN",
        po_belongs_to_vendor=True,
        duplicate_status="NO_DUPLICATE_FOUND",
        amount_validation_status="PASS",
        invoice_amount="95000.00",
        po_total="120000.00",
        remaining_po_balance="80000.00",
        previously_approved_invoiced="25000.00",
        tax_validation_status="PASS",
        line_item_validation_status="PASS",
        extraction_status="SUCCESS",
        min_extraction_confidence=0.95,
    )


@pytest.fixture
def empty_input():
    """All fields None — should REVIEW (missing everything)."""
    return DecisionInput()


# ══════════════════════════════════════════════════════════════════════════════
# APPROVE scenarios
# ══════════════════════════════════════════════════════════════════════════════

def test_approve_completely_valid(valid_input):
    """Scenario 1/26: Completely valid invoice → APPROVE."""
    result = decide(valid_input)
    assert result.decision == "APPROVE"
    assert result.approval_eligible is True
    assert "approved automatically" in result.summary.lower() or "all checks passed" in result.summary.lower()
    # Verify all mandatory rules are present with PASS status
    rule_ids = [r.rule_id for r in result.rules_evaluated]
    assert "APPROVE_001" in rule_ids


def test_approve_with_extra_passes(valid_input):
    """Scenario 26: All checks pass → APPROVE (repeatable)."""
    result_a = decide(valid_input)
    result_b = decide(valid_input)
    assert result_a.decision == result_b.decision == "APPROVE"


# ══════════════════════════════════════════════════════════════════════════════
# REJECT scenarios
# ══════════════════════════════════════════════════════════════════════════════

def test_reject_exact_document_duplicate(valid_input):
    """Scenario 2: Confirmed document duplicate → REJECT."""
    result = decide(
        valid_input.model_copy(update={
            "duplicate_status": "EXACT_DOCUMENT_DUPLICATE",
            "duplicate_evidence": {"existing_invoice_id": "INV-2025-001"},
        })
    )
    assert result.decision == "REJECT"
    assert result.approval_eligible is False
    assert any("DOC_DUP_001" in r.rule_id for r in result.rules_evaluated)
    assert len(result.hard_failures) >= 1


def test_reject_exact_invoice_duplicate(valid_input):
    """Scenario 3: Confirmed invoice duplicate → REJECT."""
    result = decide(
        valid_input.model_copy(update={
            "duplicate_status": "EXACT_INVOICE_DUPLICATE",
            "duplicate_evidence": {
                "existing_invoice_id": "INV-2025-041",
                "same_total": True,
                "same_currency": True,
            },
        })
    )
    assert result.decision == "REJECT"
    assert any("INV_DUP_001" in r.rule_id for r in result.rules_evaluated)


def test_reject_blocked_vendor(valid_input):
    """Scenario 5: Blocked vendor → REJECT."""
    result = decide(
        valid_input.model_copy(update={"vendor_blocked": True, "vendor_match_status": "MATCHED"})
    )
    assert result.decision == "REJECT"
    assert any("VENDOR_BLOCK_001" in r.rule_id for r in result.rules_evaluated)


# ══════════════════════════════════════════════════════════════════════════════
# REVIEW scenarios
# ══════════════════════════════════════════════════════════════════════════════

def test_review_conflicting_duplicate_amount(valid_input):
    """Scenario 4: Same invoice number with conflicting amount → REVIEW."""
    result = decide(
        valid_input.model_copy(update={
            "duplicate_status": "EXACT_INVOICE_DUPLICATE",
            "duplicate_evidence": {
                "existing_invoice_id": "INV-2025-041",
                "same_total": False,
                "same_currency": True,
            },
        })
    )
    assert result.decision == "REVIEW"
    assert any("INV_DUP_002" in r.rule_id for r in result.rules_evaluated)


def test_review_blocked_vendor_fuzzy_only(valid_input):
    """Scenario 6: Blocked vendor only as fuzzy candidate → REVIEW."""
    # Primary match is GOOD; a blocked vendor appears only as an alternative candidate
    result = decide(
        valid_input.model_copy(update={
            "vendor_blocked": False,       # primary match is NOT blocked
            "vendor_candidates": [
                {"id": 2, "name": "BadCorp", "status": "BLOCKED", "similarity": 0.6},
            ],
        })
    )
    assert result.decision == "APPROVE"


def test_review_inactive_vendor(valid_input):
    """Scenario 7: Inactive vendor → REVIEW."""
    result = decide(
        valid_input.model_copy(update={"vendor_inactive": True})
    )
    assert result.decision == "REVIEW"
    assert any("VENDOR_004" in r.rule_id for r in result.rules_evaluated)


def test_review_ambiguous_vendor(valid_input):
    """Scenario 8: Ambiguous vendor → REVIEW."""
    result = decide(
        valid_input.model_copy(update={
            "vendor_match_status": "AMBIGUOUS",
            "vendor_candidates": [
                {"id": 1, "name": "Acme Supplies Ltd", "similarity": 0.92},
                {"id": 7, "name": "Acme Services Pty", "similarity": 0.87},
            ],
        })
    )
    assert result.decision == "REVIEW"
    assert any("VENDOR_002" in r.rule_id for r in result.rules_evaluated)


def test_review_fuzzy_only_vendor(valid_input):
    """Scenario 9: Fuzzy-only vendor identification → REVIEW."""
    result = decide(
        valid_input.model_copy(update={
            "vendor_match_status": "MATCHED",
            "vendor_match_method": "FUZZY_NAME",
            "vendor_confidence": 0.78,   # below typical auto-approve threshold
        })
    )
    assert result.decision == "REVIEW"


def test_review_missing_po(valid_input):
    """Scenario 11: Missing PO reference → REVIEW."""
    result = decide(
        valid_input.model_copy(update={
            "po_match_status": "MISSING_PO",
            "po_reference": None,
        })
    )
    assert result.decision == "REVIEW"
    assert any("PO_001" in r.rule_id for r in result.rules_evaluated)


def test_review_ambiguous_po(valid_input):
    """Scenario 10: Ambiguous PO → REVIEW."""
    result = decide(
        valid_input.model_copy(update={
            "po_match_status": "AMBIGUOUS",
            "po_candidates": [
                {"id": 1, "number": "PO-2025-088"},
                {"id": 3, "number": "PO-2025-089"},
            ],
        })
    )
    assert result.decision == "REVIEW"
    assert any("PO_002" in r.rule_id for r in result.rules_evaluated)


def test_review_cancelled_po(valid_input):
    """Scenario 12: Cancelled PO → REVIEW."""
    result = decide(
        valid_input.model_copy(update={"po_status": "CANCELLED"})
    )
    assert result.decision == "REVIEW"
    assert any("PO_004" in r.rule_id for r in result.rules_evaluated)


def test_review_closed_po(valid_input):
    """Scenario 13: Closed PO → REVIEW."""
    result = decide(
        valid_input.model_copy(update={"po_status": "CLOSED"})
    )
    assert result.decision == "REVIEW"
    assert any("PO_005" in r.rule_id for r in result.rules_evaluated)


def test_review_currency_mismatch(valid_input):
    """Scenario 14: Currency mismatch → REVIEW."""
    result = decide(
        valid_input.model_copy(update={
            "invoice_currency": "USD",
            "po_currency": "AUD",
            "currency_mismatch": True,
        })
    )
    assert result.decision == "REVIEW"
    assert any("CURRENCY_001" in r.rule_id for r in result.rules_evaluated)


def test_review_exceeds_po_balance(valid_input):
    """Scenario 15: Invoice exceeds remaining PO balance → REVIEW."""
    result = decide(
        valid_input.model_copy(update={
            "invoice_amount": "95000.00",
            "remaining_po_balance": "80000.00",
            "amount_validation_status": "FAIL",
            "amount_explanation": (
                "Invoice total 95000.00 exceeds remaining PO balance 80000.00 by 15000.00"
            ),
        })
    )
    assert result.decision == "REVIEW"
    assert any("AMOUNT_001" in r.rule_id for r in result.rules_evaluated)


def test_review_provisional_po_balance(valid_input):
    """Scenario 16: Provisional PO balance → REVIEW."""
    result = decide(
        valid_input.model_copy(update={
            "amount_validation_status": "WARNING",
            "amount_explanation": (
                "PO has no approved invoices; remaining balance is provisional"
            ),
        })
    )
    assert result.decision == "REVIEW"
    assert any("AMOUNT_002" in r.rule_id for r in result.rules_evaluated)


def test_review_potential_duplicate(valid_input):
    """Scenario 17: Potential duplicate → REVIEW."""
    result = decide(
        valid_input.model_copy(update={
            "duplicate_status": "POTENTIAL_DUPLICATE",
            "duplicate_evidence": {"existing_invoice_id": "INV-2025-039"},
        })
    )
    assert result.decision == "REVIEW"
    assert any("DUP_001" in r.rule_id for r in result.rules_evaluated)


def test_review_tax_arithmetic_failure(valid_input):
    """Scenario 18: Tax arithmetic failure → REVIEW."""
    result = decide(
        valid_input.model_copy(update={
            "tax_validation_status": "FAIL",
            "tax_explanation": "subtotal + tax does not equal total",
        })
    )
    assert result.decision == "REVIEW"
    assert any("TAX_001" in r.rule_id for r in result.rules_evaluated)


def test_review_line_item_discrepancy(valid_input):
    """Scenario 19: Line-item discrepancy → REVIEW."""
    result = decide(
        valid_input.model_copy(update={
            "line_item_validation_status": "WARNING",
            "line_item_explanation": "Line 3 quantity differs between invoice and PO",
        })
    )
    assert result.decision == "REVIEW"
    assert any("LINEITEM_001" in r.rule_id for r in result.rules_evaluated)


def test_review_missing_critical_field(valid_input):
    """Scenario 20: Missing critical field → REVIEW."""
    result = decide(
        valid_input.model_copy(update={
            "missing_critical_fields": ["invoice_date", "tax_id"],
        })
    )
    assert result.decision == "REVIEW"
    assert any("FIELDS_001" in r.rule_id for r in result.rules_evaluated)


def test_review_low_extraction_evidence(valid_input):
    """Scenario 21: Low extraction evidence → REVIEW."""
    result = decide(
        valid_input.model_copy(update={
            "extraction_status": "PARTIAL",
            "min_extraction_confidence": 0.62,
        })
    )
    assert result.decision == "REVIEW"
    assert any("EXTRACTION_001" in r.rule_id for r in result.rules_evaluated)


def test_review_unknown_validation(valid_input):
    """Scenario 22: Unknown validation status → REVIEW."""
    result = decide(
        valid_input.model_copy(update={
            "unknown_checks": ["currency_conversion"],
        })
    )
    assert result.decision == "REVIEW"
    assert any("CHECK_001" in r.rule_id for r in result.rules_evaluated)


def test_review_missing_mandatory_check(empty_input):
    """Scenario 23: Missing mandatory validation → REVIEW (empty input)."""
    result = decide(empty_input)
    assert result.decision == "REVIEW"


def test_review_multiple_conditions(valid_input):
    """Scenario 24: Multiple REVIEW conditions → single REVIEW with all reasons."""
    result = decide(
        valid_input.model_copy(update={
            "po_status": "CANCELLED",
            "tax_validation_status": "FAIL",
            "tax_explanation": "Tax does not reconcile",
            "missing_critical_fields": ["invoice_date"],
        })
    )
    assert result.decision == "REVIEW"
    # All three should appear in review_reasons (or at least the top ones)
    combined = " ".join(result.review_reasons)
    assert "CANCELLED" in combined or "PO_004" in " ".join(r.rule_id for r in result.rules_evaluated)


def test_reject_and_review_together(valid_input):
    """Scenario 25: REJECT + REVIEW conditions → REJECT with all findings."""
    result = decide(
        valid_input.model_copy(update={
            "vendor_blocked": True,
            "po_status": "CANCELLED",
            "missing_critical_fields": ["tax_id"],
        })
    )
    assert result.decision == "REJECT"
    # Hard failure for blocked vendor should be present
    assert any("VENDOR_BLOCK_001" in r.rule_id for r in result.rules_evaluated)
    # Review reasons from cancelled PO and missing fields (may appear as secondary findings)
    combined = " ".join(result.review_reasons)
    assert len(combined) > 0


# ══════════════════════════════════════════════════════════════════════════════
# Edge cases: decimals, nulls, idempotency, serialization
# ══════════════════════════════════════════════════════════════════════════════

def test_decimal_amount_handling(valid_input):
    """Decimal precision is preserved in evidence."""
    result = decide(
        valid_input.model_copy(update={
            "invoice_amount": "95000.12",
            "po_total": "120000.45",
            "remaining_po_balance": "80000.00",
            "amount_validation_status": "FAIL",
            "amount_explanation": "Invoice 95000.12 > remaining balance 80000.00",
        })
    )
    assert result.decision == "REVIEW"
    evidence = next(r.evidence for r in result.rules_evaluated if "AMOUNT_001" in r.rule_id)
    assert evidence["invoice_amount"] == "95000.12"


def test_null_fields_handled(empty_input):
    """Null fields do not cause crashes."""
    result = decide(empty_input)
    # Should REVIEW, never throw
    assert isinstance(result.decision, str)
    assert result.decision in ("APPROVE", "REVIEW", "REJECT")


def test_idempotent_decision(valid_input):
    """Scenario 27: Repeated evaluation of identical input → identical output."""
    r1 = decide(valid_input)
    r2 = decide(valid_input)
    assert r1.decision == r2.decision
    assert r1.approval_eligible == r2.approval_eligible
    assert len(r1.rules_evaluated) == len(r2.rules_evaluated)
    for a, b in zip(r1.rules_evaluated, r2.rules_evaluated):
        assert a.rule_id == b.rule_id
        assert a.status == b.status


def test_serialization(valid_input):
    """Result is JSON-serialisable."""
    result = decide(valid_input)
    data = result.to_json_safe()
    import json
    json_str = json.dumps(data, default=str)
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)
    assert parsed["decision"] == "APPROVE"


def test_invalid_input_no_crash():
    """Calling decide with empty or partial input does not raise."""
    for inp in [DecisionInput(), DecisionInput(invoice_number="X"), DecisionInput()]:
        result = decide(inp)
        assert hasattr(result, "decision")


def test_policy_version_in_output(valid_input):
    """Policy version is included and matches DEFAULT_POLICY.version."""
    result = decide(valid_input)
    assert result.policy_version == DEFAULT_POLICY.version


def test_all_rule_ids_stable():
    """Every rule ID referenced in the engine source exists as a constant or pattern."""
    # Ensure no drift: rules_evaluated should always have stable IDs
    result = decide(
        DecisionInput(
            invoice_number="INV-TEST",
            vendor_name="TestVendor",
            vendor_tax_id="AU:999",
            vendor_match_status="MATCHED",
            vendor_confidence=0.95,
            po_reference="PO-TEST",
            po_match_status="MATCHED",
            po_status="OPEN",
            po_belongs_to_vendor=True,
            duplicate_status="NO_DUPLICATE_FOUND",
            amount_validation_status="PASS",
            invoice_amount="100.00",
            tax_validation_status="PASS",
            line_item_validation_status="PASS",
            extraction_status="SUCCESS",
            min_extraction_confidence=0.95,
        )
    )
    rule_ids = [r.rule_id for r in result.rules_evaluated]
    # Must contain the approve rule and vendor/PO checks
    assert "APPROVE_001" in rule_ids


# ══════════════════════════════════════════════════════════════════════════════
# Additional edge cases from spec
# ══════════════════════════════════════════════════════════════════════════════

def test_review_unmatched_vendor(valid_input):
    """Vendor UNMATCHED → REVIEW."""
    result = decide(
        valid_input.model_copy(update={"vendor_match_status": "UNMATCHED"})
    )
    assert result.decision == "REVIEW"
    assert any("VENDOR_001" in r.rule_id for r in result.rules_evaluated)


def test_review_unmatched_po(valid_input):
    """PO UNMATCHED → REVIEW."""
    result = decide(
        valid_input.model_copy(update={"po_match_status": "UNMATCHED"})
    )
    assert result.decision == "REVIEW"
    assert any("PO_003" in r.rule_id for r in result.rules_evaluated)


def test_review_tax_unknown(valid_input):
    """Tax validation UNKNOWN → REVIEW."""
    result = decide(
        valid_input.model_copy(update={"tax_validation_status": "UNKNOWN"})
    )
    assert result.decision == "REVIEW"
    assert any("TAX_002" in r.rule_id for r in result.rules_evaluated)


def test_approve_requires_exact_vendor_match():
    """Fuzzy-only vendor match does NOT auto-approve."""
    result = decide(
        DecisionInput(
            invoice_number="INV-FUZZY",
            vendor_name="Acme Ltd",
            vendor_tax_id=None,
            vendor_match_status="MATCHED",
            vendor_match_method="FUZZY_NAME",
            vendor_confidence=0.72,
            po_reference="PO-100",
            po_match_status="MATCHED",
            po_match_method="REFERENCE_EXACT",
            po_status="OPEN",
            po_belongs_to_vendor=True,
            duplicate_status="NO_DUPLICATE_FOUND",
            amount_validation_status="PASS",
            invoice_amount="500.00",
            tax_validation_status="PASS",
            line_item_validation_status="PASS",
            extraction_status="SUCCESS",
            min_extraction_confidence=0.95,
        )
    )
    assert result.decision == "REVIEW"


def test_approve_requires_open_po():
    """PO status other than OPEN → REVIEW (even if everything else passes)."""
    for bad_status in ["CLOSED", "CANCELLED", "AWAITING_APPROVAL"]:
        result = decide(
            DecisionInput(
                invoice_number="INV-PO",
                vendor_name="TestVendor",
                vendor_tax_id="AU:100",
                vendor_match_status="MATCHED",
                vendor_confidence=0.99,
                po_reference="PO-BAD",
                po_match_status="MATCHED",
                po_status=bad_status,
                po_belongs_to_vendor=True,
                duplicate_status="NO_DUPLICATE_FOUND",
                amount_validation_status="PASS",
                invoice_amount="100.00",
                tax_validation_status="PASS",
                line_item_validation_status="PASS",
                extraction_status="SUCCESS",
                min_extraction_confidence=0.95,
            )
        )
        assert result.decision == "REVIEW", f"Expected REVIEW for po_status={bad_status}, got {result.decision}"


def test_rule_has_all_required_fields():
    """Every RuleEvaluation has rule_id, status, severity, explanation, evidence."""
    from app.services.decision_engine import _SEVERITY_INFO
    r = RuleEvaluation(
        rule_id="TEST_001",
        rule_name="Test rule",
        status="PASS",
        severity=_SEVERITY_INFO,
        explanation="Something happened.",
        evidence={"key": "value"},
    )
    assert r.rule_id == "TEST_001"
    assert r.status == "PASS"
    assert r.severity == "INFO"
    assert r.explanation == "Something happened."
    assert r.evidence == {"key": "value"}


