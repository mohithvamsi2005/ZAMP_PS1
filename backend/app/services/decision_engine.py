"""Deterministic invoice decision engine — pure business-rule evaluation.

Consumes structured matching/validation results from Phase 4 and produces a
single final outcome: APPROVE | REVIEW | REJECT, with full explanations.

The LLM is never consulted for the decision. All logic is deterministic Python.
No database side effects. No hidden external dependencies.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from app.schemas.decision import DecisionInput, DecisionResult, RuleEvaluation
from app.core.decision_policy import DecisionPolicy, DEFAULT_POLICY

logger = logging.getLogger(__name__)


# ── Severity constants ────────────────────────────────────────────────────────
_SEVERITY_REJECT = "REJECT"
_SEVERITY_REVIEW = "REVIEW"
_SEVERITY_INFO = "INFO"
_SEVERITY_WARNING = "WARNING"

# ── Status mapping: upstream status → decision severity ───────────────────────
# Mapping used when an upstream check produces a non-PASS status that maps
# to either REVIEW or REJECT in the final decision.


def _rule(
    rule_id: str,
    rule_name: str,
    status: str,
    severity: str,
    explanation: str,
    evidence: Optional[dict] = None,
) -> RuleEvaluation:
    """Helper to create a RuleEvaluation with sensible defaults."""
    return RuleEvaluation(
        rule_id=rule_id,
        rule_name=rule_name,
        status=status,
        severity=severity,
        explanation=explanation,
        evidence=evidence or {},
    )


# ── Core evaluation function ─────────────────────────────────────────────────

def decide(input_data: DecisionInput, policy: DecisionPolicy = DEFAULT_POLICY) -> DecisionResult:
    """Evaluate all decision rules and return the final deterministic outcome.

    Precedence: REJECT > REVIEW > APPROVE.
    Every applicable rule is evaluated — later passing rules cannot override
    a prior hard rejection or review condition.
    """
    rules: List[RuleEvaluation] = []
    hard_failures: List[str] = []
    review_reasons: List[str] = []

    # ════════════════════════════════════════════════════════════════════════
    # PHASE A — REJECT conditions (hard failures, highest precedence)
    # ════════════════════════════════════════════════════════════════════════

    # Rule 1: Confirmed duplicate document (SHA-256)
    if input_data.duplicate_status == "EXACT_DOCUMENT_DUPLICATE":
        dup_ev = input_data.duplicate_evidence or {}
        r = _rule(
            rule_id="DOC_DUP_001",
            rule_name="Confirmed document duplicate",
            status="FAIL",
            severity=_SEVERITY_REJECT,
            explanation=(
                f"Document hash matches an already-processed invoice "
                f"(existing_invoice_id={dup_ev.get('existing_invoice_id', 'unknown')}). "
                f"Rejecting to prevent double payment."
            ),
            evidence={"duplicate_type": "document_hash", **dup_ev},
        )
        rules.append(r)
        hard_failures.append(r.explanation)

    # Rule 2a: Confirmed duplicate invoice — REJECT only when financials are consistent
    if input_data.duplicate_status == "EXACT_INVOICE_DUPLICATE":
        dup_ev = input_data.duplicate_evidence or {}
        is_confirmed_same = (
            dup_ev.get("same_total") is not False
            and dup_ev.get("same_currency") is not False
        )
        if is_confirmed_same:
            r = _rule(
                rule_id="INV_DUP_001",
                rule_name="Confirmed invoice duplicate",
                status="FAIL",
                severity=_SEVERITY_REJECT,
                explanation=(
                    f"Vendor {input_data.vendor_name} already has invoice number "
                    f"{input_data.invoice_number or 'unknown'} in the system "
                    f"(existing_invoice_id={dup_ev.get('existing_invoice_id', 'unknown')}). "
                    f"Rejecting duplicate submission."
                ),
                evidence={
                    "duplicate_type": "invoice_number",
                    "vendor_name": input_data.vendor_name,
                    "invoice_number": input_data.invoice_number,
                    **dup_ev,
                },
            )
            rules.append(r)
            hard_failures.append(r.explanation)
        else:
            # Conflicting financials — fall through to REVIEW (Rule 2b below)
            pass

    # Rule 2b: Same invoice number but conflicting financial details → REVIEW
    if (input_data.duplicate_status == "EXACT_INVOICE_DUPLICATE" and
            input_data.duplicate_evidence):
        ev = input_data.duplicate_evidence
        is_confirmed_same = (
            ev.get("same_total") is not False
            and ev.get("same_currency") is not False
        )
        if not is_confirmed_same:
            r = _rule(
                rule_id="INV_DUP_002",
                rule_name="Invoice duplicate with conflicting financials",
                status="WARNING",
                severity=_SEVERITY_REVIEW,
                explanation=(
                    f"Same invoice number as existing invoice {ev.get('invoice_number')}, "
                    f"but financial details differ (same_total={ev.get('same_total')}, "
                    f"same_currency={ev.get('same_currency')}). Flagging for review."
                ),
                evidence=ev,
            )
            rules.append(r)
            review_reasons.append(r.explanation)

    # Rule 3: Blocked vendor (exact, unambiguous match only)
    if policy.reject_on_blocked_vendor and input_data.vendor_blocked is True:
        r = _rule(
            rule_id="VENDOR_BLOCK_001",
            rule_name="Blocked vendor",
            status="FAIL",
            severity=_SEVERITY_REJECT,
            explanation=(
                f"Vendor '{input_data.vendor_name}' is BLOCKED in the procurement system. "
                f"Invoices from blocked vendors are not eligible for approval."
            ),
            evidence={"vendor_name": input_data.vendor_name, "vendor_status": "BLOCKED"},
        )
        rules.append(r)
        hard_failures.append(r.explanation)

    # ════════════════════════════════════════════════════════════════════════
    # PHASE B — REVIEW conditions
    # ════════════════════════════════════════════════════════════════════════

    # Rule 4: Missing critical invoice fields
    if policy.review_on_missing_critical_fields and input_data.missing_critical_fields:
        r = _rule(
            rule_id="FIELDS_001",
            rule_name="Missing critical invoice fields",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"The following required fields are missing or null: "
                f"{', '.join(input_data.missing_critical_fields)}. "
                f"Cannot make a reliable decision without this information."
            ),
            evidence={"missing_fields": input_data.missing_critical_fields},
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 5: Vendor matching — UNMATCHED
    if policy.review_on_unmatched_vendor and input_data.vendor_match_status == "UNMATCHED":
        r = _rule(
            rule_id="VENDOR_001",
            rule_name="Vendor verification",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"No vendor found in the procurement database for name='{input_data.vendor_name}' "
                f"or tax_id='{input_data.vendor_tax_id}'. "
                f"Human must identify or register the vendor before proceeding."
            ),
            evidence={
                "vendor_name": input_data.vendor_name,
                "vendor_tax_id": input_data.vendor_tax_id,
                "match_method": input_data.vendor_match_method,
                "confidence": input_data.vendor_confidence,
            },
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 6: Vendor matching — AMBIGUOUS (multiple plausible candidates)
    if policy.review_on_ambiguous_vendor and input_data.vendor_match_status == "AMBIGUOUS":
        r = _rule(
            rule_id="VENDOR_002",
            rule_name="Ambiguous vendor match",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"Multiple plausible vendor matches found for "
                f"'{input_data.vendor_name}'. Confidence insufficient for automatic approval. "
                f"Candidates: {len(input_data.vendor_candidates)}. "
                f"Human must confirm the intended vendor."
            ),
            evidence={
                "vendor_name": input_data.vendor_name,
                "candidate_count": len(input_data.vendor_candidates),
                "candidates": input_data.vendor_candidates,
            },
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 7: Vendor matching — NEEDS_REVIEW (blocked vendor matched but not auto-rejected per policy)
    if (policy.review_on_needs_review_vendor and
            input_data.vendor_match_status == "NEEDS_REVIEW" and
            not input_data.vendor_blocked):
        r = _rule(
            rule_id="VENDOR_003",
            rule_name="Vendor requires manual review",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"Vendor '{input_data.vendor_name}' was matched but flagged for manual review "
                f"(status={input_data.vendor_match_status}). Confidence={input_data.vendor_confidence}. "
                f"Human must verify vendor eligibility before approval."
            ),
            evidence={
                "vendor_name": input_data.vendor_name,
                "match_method": input_data.vendor_match_method,
                "confidence": input_data.vendor_confidence,
            },
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 8: Inactive vendor (not blocked — REVIEW, not auto-approve or reject)
    if policy.review_on_inactive_vendor and input_data.vendor_inactive is True:
        r = _rule(
            rule_id="VENDOR_004",
            rule_name="Inactive vendor",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"Vendor '{input_data.vendor_name}' is INACTIVE in the procurement system. "
                f"Inactive vendors cannot be auto-approved; human must confirm eligibility."
            ),
            evidence={"vendor_name": input_data.vendor_name, "vendor_status": "INACTIVE"},
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 9: Fuzzy-only vendor match → REVIEW (per spec: fuzzy matches must go to REVIEW)
    if policy.review_on_ambiguous_vendor and input_data.vendor_match_status == "MATCHED":
        method = input_data.vendor_match_method or ""
        is_fuzzy = any(kw in method.upper() for kw in ("FUZZY", "SIMILARITY"))
        confidence = input_data.vendor_confidence or 0.0
        if is_fuzzy and confidence < 0.95:
            r = _rule(
                rule_id="VENDOR_005",
                rule_name="Fuzzy-only vendor identification",
                status="WARNING",
                severity=_SEVERITY_REVIEW,
                explanation=(
                    f"Vendor '{input_data.vendor_name}' was matched via fuzzy matching "
                    f"(method={input_data.vendor_match_method}, confidence={confidence}). "
                    f"Fuzzy-only matches require human confirmation before auto-approval."
                ),
                evidence={
                    "vendor_name": input_data.vendor_name,
                    "match_method": input_data.vendor_match_method,
                    "confidence": confidence,
                },
            )
            rules.append(r)
            review_reasons.append(r.explanation)

    # Rule 10: PO matching — MISSING_PO
    if policy.review_on_missing_po and input_data.po_match_status == "MISSING_PO":
        r = _rule(
            rule_id="PO_001",
            rule_name="Purchase order reference missing",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"No PO reference provided and no vendor match available to search by. "
                f"Cannot verify that this invoice corresponds to an approved purchase order."
            ),
            evidence={
                "po_reference": input_data.po_reference,
                "vendor_match_status": input_data.vendor_match_status,
            },
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 10: PO matching — AMBIGUOUS
    if policy.review_on_ambiguous_po and input_data.po_match_status == "AMBIGUOUS":
        r = _rule(
            rule_id="PO_002",
            rule_name="Ambiguous PO match",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"Multiple candidate POs found for the invoice. "
                f"Cannot auto-select one; human must confirm which PO this invoice relates to."
            ),
            evidence={
                "po_reference": input_data.po_reference,
                "candidate_count": len(input_data.po_candidates),
                "candidates": input_data.po_candidates,
            },
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 11: PO matching — UNMATCHED (reference provided but not found)
    if policy.review_on_unmatched_po and input_data.po_match_status == "UNMATCHED":
        r = _rule(
            rule_id="PO_003",
            rule_name="PO reference not found",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"PO reference '{input_data.po_reference}' was not found in the procurement system. "
                f"Human must verify the PO number or confirm this is a non-PO invoice."
            ),
            evidence={"po_reference": input_data.po_reference},
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 12: Cancelled PO
    if policy.review_on_cancelled_po and input_data.po_status == "CANCELLED":
        r = _rule(
            rule_id="PO_004",
            rule_name="Cancelled purchase order",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"PO {input_data.po_reference} is CANCELLED. "
                f"Invoices against cancelled POs require human review before any action."
            ),
            evidence={"po_number": input_data.po_reference, "po_status": "CANCELLED"},
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 13: Closed PO (not auto-reject per spec — REVIEW)
    if policy.review_on_closed_po and input_data.po_status == "CLOSED":
        r = _rule(
            rule_id="PO_005",
            rule_name="Closed purchase order",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"PO {input_data.po_reference} is CLOSED. "
                f"Invoices against closed POs require human review."
            ),
            evidence={"po_number": input_data.po_reference, "po_status": "CLOSED"},
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 13b: Fuzzy-only PO match → REVIEW (per spec: fuzzy matches must go to REVIEW)
    if policy.review_on_ambiguous_po and input_data.po_match_status == "MATCHED":
        method = input_data.po_match_method or ""
        is_fuzzy = any(kw in method.upper() for kw in ("FUZZY", "SIMILARITY"))
        confidence = input_data.po_confidence or 0.0
        if is_fuzzy and confidence < 0.95:
            r = _rule(
                rule_id="PO_006",
                rule_name="Fuzzy-only PO identification",
                status="WARNING",
                severity=_SEVERITY_REVIEW,
                explanation=(
                    f"PO matched via fuzzy matching (method={input_data.po_match_method}, "
                    f"confidence={confidence}). Fuzzy-only PO matches require human confirmation."
                ),
                evidence={
                    "po_reference": input_data.po_reference,
                    "match_method": input_data.po_match_method,
                    "confidence": confidence,
                },
            )
            rules.append(r)
            review_reasons.append(r.explanation)

    # Rule 13d: PO identified by vendor candidacy alone (no reference anywhere
    # on the invoice, or a low-confidence inferred match) → REVIEW.
    # The plan calls this out explicitly: candidate PO selection without
    # document evidence never auto-approves (require_unique_po_candidate).
    if (policy.review_on_ambiguous_po and
            input_data.po_match_status == "MATCHED"):
        method = (input_data.po_match_method or "").upper()
        confidence = input_data.po_confidence
        is_bare_candidate = method == "CANDIDATE_VENDOR"
        is_weak_inferred = (
            confidence is not None
            and float(confidence) < 0.9
            and method != "EXACT_PO_NUMBER"
        )
        if is_bare_candidate or is_weak_inferred:
            r = _rule(
                rule_id="PO_008",
                rule_name="PO not evidenced on the invoice",
                status="WARNING",
                severity=_SEVERITY_REVIEW,
                explanation=(
                    f"No PO reference appeared on the invoice, so the system matched a PO "
                    f"from vendor context alone (method={input_data.po_match_method}, "
                    f"confidence={confidence}). A human must confirm that this invoice "
                    f"corresponds to that purchase order."
                ),
                evidence={
                    "po_reference": input_data.po_reference,
                    "match_method": input_data.po_match_method,
                    "confidence": input_data.po_confidence,
                },
            )
            rules.append(r)
            review_reasons.append(r.explanation)

    # Rule 13c: PO present but not OPEN (e.g. AWAITING_APPROVAL, HELD) — REVIEW
    _KNOWN_OPEN_STATUSES = {"OPEN"}
    if input_data.po_match_status == "MATCHED" and input_data.po_status not in _KNOWN_OPEN_STATUSES:
        po_status = input_data.po_status or "UNKNOWN"
        r = _rule(
            rule_id="PO_007",
            rule_name="Purchase order not open",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"PO {input_data.po_reference} has status '{po_status}'. "
                f"Only OPEN POs are eligible for automatic approval. Human must confirm eligibility."
            ),
            evidence={"po_number": input_data.po_reference, "po_status": po_status},
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 14: Currency mismatch between invoice and PO
    if policy.review_on_currency_mismatch and input_data.currency_mismatch is True:
        r = _rule(
            rule_id="CURRENCY_001",
            rule_name="Currency mismatch",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"Invoice currency ({input_data.invoice_currency}) does not match "
                f"PO currency ({input_data.po_currency}). "
                f"Amount comparison is unreliable without currency conversion."
            ),
            evidence={
                "invoice_currency": input_data.invoice_currency,
                "po_currency": input_data.po_currency,
            },
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 15: Amount exceeds remaining PO balance
    if (policy.review_on_amount_exceeds_balance and
            input_data.amount_validation_status == "FAIL"):
        r = _rule(
            rule_id="AMOUNT_001",
            rule_name="PO balance verification",
            status="FAIL",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"Invoice amount {input_data.invoice_amount} exceeds the remaining PO balance. "
                f"{input_data.amount_explanation or ''}"
            ),
            evidence={
                "invoice_amount": input_data.invoice_amount,
                "po_total": input_data.po_total,
                "remaining_balance": input_data.remaining_po_balance,
                "previously_approved_invoiced": input_data.previously_approved_invoiced,
            },
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 16: Provisional PO balance (no APPROVE decisions exist — balance is provisional)
    if policy.review_on_provisional_po_balance and input_data.amount_validation_status == "WARNING":
        r = _rule(
            rule_id="AMOUNT_002",
            rule_name="Provisional PO balance",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"PO balance is provisional: no approved invoices exist for this PO "
                f"to confirm historical billing. Amount comparison may be unreliable."
            ),
            evidence={
                "invoice_amount": input_data.invoice_amount,
                "po_total": input_data.po_total,
                "previously_approved_invoiced": input_data.previously_approved_invoiced,
            },
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 17: Potential duplicate (not exact — REVIEW)
    if policy.review_on_potential_duplicate and input_data.duplicate_status == "POTENTIAL_DUPLICATE":
        r = _rule(
            rule_id="DUP_001",
            rule_name="Potential duplicate invoice",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"Suspicious similarity with an existing invoice. "
                f"Same vendor and similar invoice number detected, but not an exact match. "
                f"Human must verify this is not a re-submission."
            ),
            evidence=input_data.duplicate_evidence or {},
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 18: Tax arithmetic failure
    if policy.review_on_tax_failure and input_data.tax_validation_status == "FAIL":
        r = _rule(
            rule_id="TAX_001",
            rule_name="Tax / arithmetic validation",
            status="FAIL",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"Invoice arithmetic is inconsistent: {input_data.tax_explanation or 'subtotal + tax - discount != total'}. "
                f"Human must verify the correct amounts."
            ),
            evidence={"tax_check": input_data.tax_explanation},
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 19: Tax validation UNKNOWN (missing fields prevent arithmetic check)
    if policy.review_on_tax_unknown and input_data.tax_validation_status == "UNKNOWN":
        r = _rule(
            rule_id="TAX_002",
            rule_name="Tax / arithmetic validation — insufficient data",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"Cannot validate invoice arithmetic: required field(s) missing. "
                f"{input_data.tax_explanation or 'Check subtotal, tax, discount, or total fields'}."
            ),
            evidence={"tax_check": input_data.tax_explanation},
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 20: Line-item discrepancy
    if policy.review_on_line_item_discrepancy and input_data.line_item_validation_status in ("FAIL", "WARNING"):
        severity = _SEVERITY_REVIEW
        r = _rule(
            rule_id="LINEITEM_001",
            rule_name="Line-item validation",
            status="WARNING" if input_data.line_item_validation_status == "WARNING" else "FAIL",
            severity=severity,
            explanation=(
                f"Line-item comparison found discrepancies: {input_data.line_item_explanation or 'see evidence'}. "
                f"Human must verify line items against the PO."
            ),
            evidence={
                "line_item_status": input_data.line_item_validation_status,
                "explanation": input_data.line_item_explanation,
            },
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # Rule 21: Low extraction evidence (confidence below threshold or bad status)
    if policy.review_on_low_extraction_evidence:
        _add_extraction_review(rules, review_reasons, input_data, policy)

    # Rule 22: Unknown validation results
    if policy.review_on_unknown_validation and input_data.unknown_checks:
        r = _rule(
            rule_id="CHECK_001",
            rule_name="Unknown validation results",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"The following validations could not be completed or returned UNKNOWN: "
                f"{', '.join(input_data.unknown_checks)}. "
                f"Cannot approve when mandatory checks are uncertain."
            ),
            evidence={"unknown_checks": input_data.unknown_checks},
        )
        rules.append(r)
        review_reasons.append(r.explanation)

    # ════════════════════════════════════════════════════════════════════════
    # PHASE C — APPROVE conditions (only if no hard failures and no reviews)
    # ════════════════════════════════════════════════════════════════════════

    approval_eligible = (
        not hard_failures and
        not review_reasons and
        input_data.vendor_match_status == "MATCHED" and
        not input_data.vendor_blocked and
        not input_data.vendor_inactive and
        input_data.po_match_status == "MATCHED" and
        (input_data.po_belongs_to_vendor is not False) and  # None means unknown; allow if not explicitly false
        input_data.po_status == "OPEN" and
        not input_data.currency_mismatch and
        input_data.duplicate_status == "NO_DUPLICATE_FOUND" and
        not input_data.missing_critical_fields and
        input_data.extraction_status in policy.acceptable_extraction_status and
        (input_data.min_extraction_confidence or 0) >= policy.min_extraction_confidence and
        input_data.amount_validation_status == "PASS" and
        input_data.tax_validation_status == "PASS" and
        input_data.line_item_validation_status == "PASS" and
        not input_data.unknown_checks
    )

    if approval_eligible:
        rules.append(_rule(
            rule_id="APPROVE_001",
            rule_name="All mandatory checks passed",
            status="PASS",
            severity=_SEVERITY_INFO,
            explanation=(
                f"Invoice {input_data.invoice_number} from vendor "
                f"{input_data.vendor_name} passed all required checks. "
                f"Vendor is active and unambiguously identified. PO is open and eligible. "
                f"Amount is within balance. Arithmetic reconciles. No duplicates found."
            ),
            evidence={
                "vendor_match": input_data.vendor_match_status,
                "po_match": input_data.po_match_status,
                "duplicate_check": input_data.duplicate_status,
                "amount_validation": input_data.amount_validation_status,
                "tax_validation": input_data.tax_validation_status,
                "line_item_validation": input_data.line_item_validation_status,
            },
        ))

    # ════════════════════════════════════════════════════════════════════════
    # Final decision assembly
    # ════════════════════════════════════════════════════════════════════════

    if hard_failures:
        final_decision = "REJECT"
        summary = (
            f"Invoice rejected: {len(hard_failures)} hard failure(s) detected. "
            + "; ".join(hard_failures[:2])
        )
    elif review_reasons or not approval_eligible:
        final_decision = "REVIEW"
        summary = (
            f"Invoice requires human verification: mandatory conditions not fully satisfied. "
            + (f"{len(review_reasons)} explicit condition(s) need review." if review_reasons else "")
        )
    else:
        final_decision = "APPROVE"
        summary = (
            f"Invoice {input_data.invoice_number} approved automatically. "
            f"All checks passed."
        )

    return DecisionResult(
        decision=final_decision,
        policy_version=policy.version,
        summary=summary,
        rules_evaluated=rules,
        hard_failures=hard_failures,
        review_reasons=review_reasons,
        approval_eligible=approval_eligible and final_decision == "APPROVE",
    )


def _add_extraction_review(
    rules: List[RuleEvaluation],
    review_reasons: List[str],
    input_data: DecisionInput,
    policy: DecisionPolicy,
) -> None:
    """Add a REVIEW rule for low or insufficient extraction evidence."""
    reasons = []

    if (input_data.min_extraction_confidence is not None and
            input_data.min_extraction_confidence < policy.min_extraction_confidence):
        reasons.append(
            f"Minimum critical-field confidence {input_data.min_extraction_confidence} "
            f"is below the required threshold of {policy.min_extraction_confidence}."
        )

    if (input_data.extraction_status is not None and
            input_data.extraction_status not in policy.acceptable_extraction_status):
        reasons.append(
            f"Extraction status is '{input_data.extraction_status}' "
            f"(expected {'/'.join(policy.acceptable_extraction_status)})."
        )

    if input_data.extraction_warnings:
        reasons.append(f"Extraction warnings: {'; '.join(input_data.extraction_warnings[:3])}")

    if reasons:
        r = _rule(
            rule_id="EXTRACTION_001",
            rule_name="Extraction evidence quality",
            status="WARNING",
            severity=_SEVERITY_REVIEW,
            explanation=(
                f"Invoice extraction evidence is insufficient for automatic approval: "
                + ". ".join(reasons)
                + " Human must verify the source document."
            ),
            evidence={
                "extraction_status": input_data.extraction_status,
                "min_confidence": input_data.min_extraction_confidence,
                "threshold": policy.min_extraction_confidence,
                "warnings": input_data.extraction_warnings,
            },
        )
        rules.append(r)
        review_reasons.append(r.explanation)


# ── Convenience: evaluate from MatchingAndValidationResult directly ───────────

def decide_from_matching_result(matching_result) -> DecisionResult:
    """Map a Phase 4 MatchingAndValidationResult into DecisionInput and run the engine.

    This is a thin adapter — it does not add logic, only bridges schemas.
    """
    from app.schemas.matching import (
        VendorMatchResult, POMatchResult, DuplicateResult,
        AmountValidationResult, LineItemValidationResult, TaxValidationResult,
    )

    # Determine vendor blocked/inactive from evidence or match method
    vendor_blocked = False
    vendor_inactive = False
    vm = matching_result.vendor_match
    if vm.matched_vendor:
        ev = vm.metadata or {}
        vendor_status = ev.get("vendor_status", "")
        vendor_blocked = vendor_status == "BLOCKED"
        vendor_inactive = vendor_status == "INACTIVE"

    # Determine PO status from evidence
    po_status = None
    pm = matching_result.po_match
    if pm.matched_po:
        ev = pm.metadata or {}
        po_status = ev.get("po_status")

    # Currency mismatch check — from amount_validation metadata
    currency_mismatch = False
    av = matching_result.amount_validation
    if av.evidence and av.evidence.get("currency_mismatch"):
        currency_mismatch = True
    elif av.status == "WARNING" and "Currency mismatch" in (av.explanation or ""):
        currency_mismatch = True

    # Provisional balance — flag when amount is WARNING but not due to currency
    provisional_balance = False
    if av.status == "WARNING" and not currency_mismatch:
        provisional_balance = True

    input_data = DecisionInput(
        vendor_name=vm.evidence.get("vendor_name") if vm.evidence else None,
        vendor_tax_id=vm.evidence.get("vendor_tax_id") if vm.evidence else None,
        vendor_match_status=vm.status,
        vendor_match_method=vm.metadata.get("match_method") if vm.metadata else None,
        vendor_confidence=vm.confidence,
        vendor_blocked=vendor_blocked,
        vendor_inactive=vendor_inactive,
        vendor_candidates=vm.candidates,
        po_reference=pm.evidence.get("po_reference") if pm.evidence else None,
        po_match_status=pm.status,
        po_match_method=pm.metadata.get("match_method") if pm.metadata else None,
        po_confidence=pm.confidence,
        po_status=po_status,
        po_belongs_to_vendor=pm.metadata.get("belongs_to_vendor", None) if pm.metadata else None,
        po_candidates=pm.candidates,
        duplicate_status=matching_result.duplicate_check.status,
        duplicate_evidence=matching_result.duplicate_check.evidence,
        amount_validation_status=av.status,
        invoice_amount=av.invoice_amount,
        po_total=av.po_total,
        remaining_po_balance=av.remaining_po_balance,
        previously_approved_invoiced=av.previously_approved_invoiced,
        amount_explanation=av.explanation,
        invoice_currency=None,  # populated from matching_input if available
        po_currency=None,
        currency_mismatch=currency_mismatch,
        tax_validation_status=matching_result.tax_validation.status,
        tax_explanation=matching_result.tax_validation.explanation,
        line_item_validation_status=matching_result.line_item_validation.status,
        line_item_explanation=matching_result.line_item_validation.explanation,
    )

    return decide(input_data)
