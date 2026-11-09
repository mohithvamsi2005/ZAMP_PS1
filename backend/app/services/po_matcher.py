"""Purchase-order matching service."""
from decimal import Decimal
from typing import Optional

from rapidfuzz import fuzz

from app.db.models import PurchaseOrder, POStatus
from app.db.session import SessionLocal
from app.schemas.matching import MatchedPO, POMatchResult
from app.services.normalizer import normalize_po_reference


def _exact_po_match(po_ref: str, db_session) -> Optional[PurchaseOrder]:
    """Return the PO whose po_number exactly matches (after normalisation), or None."""
    if not po_ref:
        return None
    norm_target = normalize_po_reference(po_ref)
    pos = db_session.query(PurchaseOrder).all()
    for po in pos:
        if normalize_po_reference(po.po_number) == norm_target:
            return po
    return None


def _candidate_matches(
    vendor_id: Optional[int],
    po_ref: Optional[str],
    db_session,
) -> list[dict]:
    """Return candidate POs for a given vendor when the PO reference is absent or ambiguous."""
    if not vendor_id:
        return []
    pos = (
        db_session.query(PurchaseOrder)
        .filter(
            PurchaseOrder.vendor_id == vendor_id,
            PurchaseOrder.status.in_([POStatus.OPEN, POStatus.CLOSED]),
        )
        .all()
    )
    if not pos:
        return []

    candidates = []
    norm_ref = normalize_po_reference(po_ref) if po_ref else ""
    for po in pos:
        score = 0
        method = "CANDIDATE_VENDOR"
        evidence = {"vendor_id": vendor_id, "po_number": po.po_number}
        if norm_ref:
            ratio = fuzz.partial_ratio(
                norm_ref, normalize_po_reference(po.po_number)
            )
            if ratio >= 70:
                score = max(score, ratio)
                method = "NORMALIZED_PO"
        else:
            score = 50  # baseline for vendor-only candidates
        candidates.append({
            "id": po.id,
            "po_number": po.po_number,
            "total_amount": str(po.total_amount),
            "currency": po.currency,
            "status": po.status.value,
            "score": score,
            "match_method": method,
            "evidence": evidence,
        })
    return candidates


def match_po(
    po_reference: Optional[str] = None,
    matched_vendor_id: Optional[int] = None,
) -> POMatchResult:
    """Match an invoice PO reference against the procurement database.

    Priority:
      1. Exact normalized PO number (restricted to matched vendor if available).
      2. Candidate search by vendor when no reference or ambiguous.
    """
    db = SessionLocal()
    try:
        norm_ref = normalize_po_reference(po_reference)

        # Level 1 — exact PO number
        if norm_ref:
            po = _exact_po_match(norm_ref, db)
            if po:
                if matched_vendor_id and po.vendor_id != matched_vendor_id:
                    return POMatchResult(
                        check_name="PO match",
                        status="AMBIGUOUS",
                        matched_po=None,
                        match_method="EXACT_PO_NUMBER",
                        confidence=0.0,
                        explanation=(
                            f"PO {po.po_number} belongs to vendor {po.vendor_id}, "
                            f"but invoice references vendor {matched_vendor_id}"
                        ),
                    )
                return POMatchResult(
                    check_name="PO match",
                    status="MATCHED",
                    matched_po=MatchedPO.from_po_model(po),
                    match_method="EXACT_PO_NUMBER",
                    confidence=1.0,
                    explanation=f"Exact PO number {po_reference} matches {po.po_number}",
                )

        # No reference or no exact match → candidate search
        candidates = _candidate_matches(matched_vendor_id, po_reference, db) if matched_vendor_id else []

        if not po_reference and not candidates:
            return POMatchResult(
                check_name="PO match",
                status="MISSING_PO",
                matched_po=None,
                match_method="NONE",
                confidence=0.0,
                explanation="No PO reference provided and no vendor match to search by",
            )

        if po_reference and not candidates:
            return POMatchResult(
                check_name="PO match",
                status="UNMATCHED",
                matched_po=None,
                match_method="NONE",
                confidence=0.0,
                explanation=f"No PO found for reference {po_reference!r}",
            )

        # Ambiguous candidates — do not auto-select
        if len(candidates) > 1:
            return POMatchResult(
                check_name="PO match",
                status="AMBIGUOUS",
                matched_po=None,
                match_method="CANDIDATE_VENDOR",
                confidence=0.0,
                explanation="Multiple candidate POs found; requires human review",
                candidates=candidates,
            )

        if len(candidates) == 1:
            c = candidates[0]
            po_obj = db.get(PurchaseOrder, c["id"])
            return POMatchResult(
                check_name="PO match",
                status="MATCHED",
                matched_po=MatchedPO.from_po_model(po_obj),
                match_method=c["match_method"],
                confidence=float(c["score"] / 100) if c["score"] else 0.5,
                explanation=f"Candidate PO {c['po_number']} selected by vendor match",
                candidates=[],
            )

        return POMatchResult(
            check_name="PO match",
            status="UNMATCHED",
            matched_po=None,
            match_method="NONE",
            confidence=0.0,
            explanation="No suitable PO candidate found",
        )
    finally:
        db.close()
