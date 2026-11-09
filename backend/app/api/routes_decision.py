"""Diagnostic decision engine endpoint — Phase 5."""
import logging
from fastapi import APIRouter, HTTPException

from app.schemas.decision import DecisionInput, DecisionResult
from app.services.decision_engine import decide
from app.core.decision_policy import DEFAULT_POLICY

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/diagnostic", tags=["decision"])


@router.post("/decide", response_model=DecisionResult)
async def diagnostic_decide(input_data: DecisionInput):
    """Run the deterministic decision engine on structured invoice data.

    Accepts a DecisionInput (mirroring Phase 4 matching/validation output plus
    extraction metadata) and returns APPROVE/REVIEW/REJECT with full explanations.

    Does NOT persist results or create processing runs — inspection only.
    """
    try:
        result = decide(input_data, policy=DEFAULT_POLICY)
        return result
    except Exception as e:
        logger.exception("Decision engine failed")
        raise HTTPException(status_code=500, detail=f"Decision engine error: {e}")


@router.get("/decide/health")
async def decision_health():
    """Verify the decision engine is importable and policy is loadable."""
    return {
        "status": "ok",
        "policy_version": DEFAULT_POLICY.version,
        "services_available": ["decision_engine"],
        "rules_configured": [
            "DOC_DUP_001 — Confirmed document duplicate → REJECT",
            "INV_DUP_001 — Confirmed invoice duplicate → REJECT",
            "VENDOR_BLOCK_001 — Blocked vendor → REJECT",
            "FIELDS_001 — Missing critical fields → REVIEW",
            "VENDOR_001 — Vendor unmatched → REVIEW",
            "VENDOR_002 — Ambiguous vendor match → REVIEW",
            "VENDOR_003 — Vendor needs review → REVIEW",
            "VENDOR_004 — Inactive vendor → REVIEW",
            "PO_001 — Missing PO reference → REVIEW",
            "PO_002 — Ambiguous PO match → REVIEW",
            "PO_003 — PO not found → REVIEW",
            "PO_004 — Cancelled PO → REVIEW",
            "PO_005 — Closed PO → REVIEW",
            "CURRENCY_001 — Currency mismatch → REVIEW",
            "AMOUNT_001 — Exceeds PO balance → REVIEW",
            "AMOUNT_002 — Provisional balance → REVIEW",
            "DUP_001 — Potential duplicate → REVIEW",
            "TAX_001 — Tax arithmetic FAIL → REVIEW",
            "TAX_002 — Tax validation UNKNOWN → REVIEW",
            "LINEITEM_001 — Line-item discrepancy → REVIEW",
            "EXTRACTION_001 — Low extraction evidence → REVIEW",
            "CHECK_001 — Unknown validation checks → REVIEW",
        ],
    }
