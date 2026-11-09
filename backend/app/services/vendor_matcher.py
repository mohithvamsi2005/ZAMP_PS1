"""Vendor matching service with tax ID, exact name, and fuzzy fallback."""
from decimal import Decimal
from typing import Optional

from rapidfuzz import fuzz, process as rfprocess

from app.db.models import Vendor, VendorStatus
from app.db.session import SessionLocal
from app.schemas.matching import (
    MatchedVendor, VendorMatchResult, CheckResult,
)
from app.services.normalizer import normalize_vendor_name, normalize_tax_id


# Configurable thresholds
VENDOR_FUZZY_THRESHOLD: int = 90       # token_sort_ratio threshold
FUZZY_CANDIDATE_LIMIT: int = 3         # how many candidates to surface


def _exact_tax_id_match(tax_id: str, db_session) -> Optional[Vendor]:
    """Return the vendor whose tax_id exactly matches (after normalisation), or None."""
    if not tax_id:
        return None
    norm_target = normalize_tax_id(tax_id)
    vendors = (
        db_session.query(Vendor)
        .filter(Vendor.tax_id.isnot(None))
        .all()
    )
    for v in vendors:
        if normalize_tax_id(v.tax_id) == norm_target:
            return v
    return None


def _exact_name_match(normalized_name: str, db_session) -> Optional[Vendor]:
    """Return the vendor whose normalized_name exactly matches, or None."""
    if not normalized_name:
        return None
    vendors = (
        db_session.query(Vendor)
        .filter(Vendor.normalized_name.isnot(None))
        .all()
    )
    for v in vendors:
        if normalize_vendor_name(v.legal_name) == normalized_name:
            return v
    return None


def _fuzzy_match(normalized_name: str, db_session) -> tuple[Optional[Vendor], list[dict]]:
    """Return best fuzzy match and up to N candidate dicts."""
    if not normalized_name:
        return None, []

    vendors = (
        db_session.query(Vendor)
        .filter(Vendor.status != VendorStatus.BLOCKED)
        .all()
    )
    if not vendors:
        return None, []

    # Normalize each vendor's legal name for fair comparison
    norm_names = [normalize_vendor_name(v.legal_name) for v in vendors]
    names = norm_names  # use normalized versions

    result = rfprocess.extractOne(
        normalized_name, names, scorer=fuzz.token_sort_ratio,
        score_cutoff=VENDOR_FUZZY_THRESHOLD,
    )
    if result is None:
        return None, []

    best_name, best_score, best_idx = result
    candidates = [
        {"id": vendors[idx].id, "vendor_code": vendors[idx].vendor_code,
         "legal_name": vendors[idx].legal_name,
         "score": int(score), "match_method": "FUZZY_NAME"}
        for name, score, idx in rfprocess.extract(
            normalized_name, names, scorer=fuzz.token_sort_ratio,
            limit=FUZZY_CANDIDATE_LIMIT, score_cutoff=VENDOR_FUZZY_THRESHOLD,
        )
    ]

    if best_score == 100:
        return vendors[best_idx], candidates[1:]

    # Multiple high-scoring candidates → ambiguous
    high_candidates = [c for c in candidates if c["score"] >= VENDOR_FUZZY_THRESHOLD]
    if len(high_candidates) > 1:
        return None, high_candidates

    return vendors[best_idx], []


def match_vendor(
    vendor_name: Optional[str] = None,
    vendor_tax_id: Optional[str] = None,
) -> VendorMatchResult:
    """Run the full vendor matching pipeline against the procurement database.

    Priority:
      1. Exact tax ID
      2. Exact normalized legal name
      3. Fuzzy name (with ambiguity handling)
    """
    db = SessionLocal()
    try:
        norm_tax = normalize_tax_id(vendor_tax_id)
        norm_name = normalize_vendor_name(vendor_name)

        # Level 1 — Tax ID
        if norm_tax:
            vendor = _exact_tax_id_match(norm_tax, db)
            if vendor:
                status = "NEEDS_REVIEW" if vendor.status == VendorStatus.BLOCKED else "MATCHED"
                return VendorMatchResult(
                    check_name="Vendor match",
                    status=status,
                    matched_vendor=MatchedVendor.from_vendor_model(vendor),
                    match_method="EXACT_TAX_ID",
                    confidence=1.0 if vendor.status == VendorStatus.ACTIVE else 0.5,
                    explanation=f"Tax ID {vendor_tax_id} matches vendor {vendor.vendor_code}",
                )

        # Level 2 — Exact normalized name
        if norm_name:
            vendor = _exact_name_match(norm_name, db)
            if vendor:
                status = "NEEDS_REVIEW" if vendor.status == VendorStatus.BLOCKED else "MATCHED"
                return VendorMatchResult(
                    check_name="Vendor match",
                    status=status,
                    matched_vendor=MatchedVendor.from_vendor_model(vendor),
                    match_method="EXACT_NAME",
                    confidence=1.0 if vendor.status == VendorStatus.ACTIVE else 0.5,
                    explanation=f"Normalized name matches vendor {vendor.vendor_code}",
                )

        # Level 3 — Fuzzy name
        if norm_name:
            vendor, candidates = _fuzzy_match(norm_name, db)
            if vendor is not None and not candidates:
                status = "NEEDS_REVIEW" if vendor.status == VendorStatus.BLOCKED else "MATCHED"
                return VendorMatchResult(
                    check_name="Vendor match",
                    status=status,
                    matched_vendor=MatchedVendor.from_vendor_model(vendor),
                    match_method="FUZZY_NAME",
                    confidence=float(vendor.status != VendorStatus.BLOCKED) * 0.95,
                    explanation=f"Fuzzy match ({VENDOR_FUZZY_THRESHOLD}+) to {vendor.vendor_code}; "
                                f"status={vendor.status.value}",
                    candidates=[c for c in candidates],
                )
            if candidates:
                return VendorMatchResult(
                    check_name="Vendor match",
                    status="AMBIGUOUS",
                    matched_vendor=None,
                    match_method="FUZZY_NAME",
                    confidence=0.0,
                    explanation="Multiple fuzzy matches found; requires human review",
                    candidates=candidates,
                )

        # No match at all
        return VendorMatchResult(
            check_name="Vendor match",
            status="UNMATCHED",
            matched_vendor=None,
            match_method="NONE",
            confidence=0.0,
            explanation=f"No vendor found for name={vendor_name!r}, tax_id={vendor_tax_id!r}",
        )
    finally:
        db.close()
