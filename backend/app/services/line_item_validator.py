"""Line-item validation — compare invoice lines against PO lines."""
from decimal import Decimal

from rapidfuzz import fuzz

from app.db.models import PurchaseOrderLine, InvoiceLine
from app.db.session import SessionLocal
from app.schemas.matching import (
    LineItemMatch, LineItemValidationResult,
)
from app.services.normalizer import safe_decimal


# Configurable thresholds
LINE_ITEM_FUZZY_THRESHOLD: int = 85
QUANTITY_TOLERANCE_PERCENT: Decimal = Decimal("0.01")   # 1%
UNIT_PRICE_TOLERANCE_PERCENT: Decimal = Decimal("0.01")  # 1%


def _normalized_desc(desc: str) -> str:
    """Lowercase, strip, collapse whitespace."""
    import re
    s = desc.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _sku_match(inv_sku: str | None, po_sku: str | None) -> bool:
    if not inv_sku or not po_sku:
        return False
    return inv_sku.strip().upper() == po_sku.strip().upper()


def _description_similarity(inv_desc: str, po_desc: str) -> tuple[int, str]:
    """Return (score, match_type)."""
    norm_inv = _normalized_desc(inv_desc)
    norm_po = _normalized_desc(po_desc)

    if norm_inv == norm_po:
        return 100, "EXACT_DESC"

    ratio = fuzz.ratio(norm_inv, norm_po)
    token_ratio = fuzz.token_sort_ratio(norm_inv, norm_po)
    partial = fuzz.partial_ratio(norm_inv, norm_po)

    best_score = max(ratio, token_ratio, partial)
    if token_ratio >= ratio and token_ratio >= partial:
        match_type = "FUZZY_DESC"
    elif partial >= ratio:
        match_type = "PARTIAL_DESC"
    else:
        match_type = "NORMALIZED_DESC"

    return best_score, match_type


def _decimal_close(a: Decimal, b: Decimal, tolerance_percent: Decimal) -> bool:
    if a == b:
        return True
    if a == 0 and b == 0:
        return True
    bigger = max(abs(a), abs(b))
    if bigger == 0:
        return True
    diff_pct = abs(a - b) / bigger * Decimal("100")
    return diff_pct <= tolerance_percent


def _decimal_diff(a: Decimal, b: Decimal) -> Decimal:
    return abs(a - b)


def validate_line_items(
    invoice_id: int,
    po_id: int | None = None,
) -> LineItemValidationResult:
    """Compare invoice line items against matched PO line items.

    Matching priority:
      1. Exact SKU match (if both have SKUs).
      2. Normalized description equality.
      3. Fuzzy description similarity above threshold.
    """
    db = SessionLocal()
    try:
        if po_id is None:
            return LineItemValidationResult(
                check_name="Line-item validation",
                status="PASS",
                explanation="No PO matched; line-item comparison skipped",
            )

        po_lines = (
            db.query(PurchaseOrderLine)
            .filter(PurchaseOrderLine.purchase_order_id == po_id)
            .order_by(PurchaseOrderLine.id)
            .all()
        )
        inv_lines = (
            db.query(InvoiceLine)
            .filter(InvoiceLine.invoice_id == invoice_id)
            .order_by(InvoiceLine.id)
            .all()
        )

        matched_items: list[LineItemMatch] = []
        used_po_indices: set[int] = set()
        unmatched_invoice: list[dict] = []
        unmatched_po: list[dict] = []

        for inv_idx, inv_line in enumerate(inv_lines):
            best_score = -1
            best_po_idx = None
            best_match_type = "NONE"

            # Try SKU match first
            if inv_line.sku:
                for po_idx, po_line in enumerate(po_lines):
                    if po_idx in used_po_indices:
                        continue
                    if _sku_match(inv_line.sku, po_line.sku):
                        best_score = 100
                        best_po_idx = po_idx
                        best_match_type = "EXACT_SKU"
                        break

            # If no SKU match, try description similarity
            if best_score < 0 and inv_line.description:
                for po_idx, po_line in enumerate(po_lines):
                    if po_idx in used_po_indices:
                        continue
                    score, mtype = _description_similarity(
                        inv_line.description, po_line.description
                    )
                    if score > best_score and score >= LINE_ITEM_FUZZY_THRESHOLD:
                        best_score = score
                        best_po_idx = po_idx
                        best_match_type = mtype

            if best_po_idx is not None:
                used_po_indices.add(best_po_idx)
                po_line = po_lines[best_po_idx]

                qty_diff = _decimal_diff(
                    safe_decimal(inv_line.quantity, Decimal("0")),
                    safe_decimal(po_line.quantity, Decimal("0")),
                ) if inv_line.quantity and po_line.quantity else None
                up_diff = _decimal_diff(
                    safe_decimal(inv_line.unit_price, Decimal("0")),
                    safe_decimal(po_line.unit_price, Decimal("0")),
                ) if inv_line.unit_price and po_line.unit_price else None

                status = "MATCHED"
                explanation_parts = []
                if qty_diff is not None:
                    inv_qty = safe_decimal(inv_line.quantity) or Decimal("0")
                    po_qty = safe_decimal(po_line.quantity) or Decimal("0")
                    if not _decimal_close(inv_qty, po_qty, QUANTITY_TOLERANCE_PERCENT):
                        status = "QUANTITY_MISMATCH"
                        explanation_parts.append(f"qty invoice={inv_qty} vs po={po_qty}")
                if up_diff is not None:
                    inv_up = safe_decimal(inv_line.unit_price) or Decimal("0")
                    po_up = safe_decimal(po_line.unit_price) or Decimal("0")
                    if not _decimal_close(inv_up, po_up, UNIT_PRICE_TOLERANCE_PERCENT):
                        status = "UNIT_PRICE_MISMATCH" if status == "MATCHED" else status
                        explanation_parts.append(f"unit_price invoice={inv_up} vs po={po_up}")

                match = LineItemMatch(
                    invoice_line_index=inv_idx,
                    po_line_index=best_po_idx,
                    status=status,
                    description_match=best_match_type,
                    invoice_description=inv_line.description,
                    po_description=po_line.description,
                    invoice_quantity=safe_decimal(inv_line.quantity),
                    po_quantity=safe_decimal(po_line.quantity),
                    invoice_unit_price=safe_decimal(inv_line.unit_price),
                    po_unit_price=safe_decimal(po_line.unit_price),
                    invoice_line_total=safe_decimal(inv_line.line_total),
                    po_line_total=safe_decimal(po_line.line_total),
                    difference=str(qty_diff) if qty_diff else None,
                    explanation="; ".join(explanation_parts) if explanation_parts else None,
                )
                matched_items.append(match)
            else:
                unmatched_invoice.append({
                    "index": inv_idx,
                    "description": inv_line.description,
                    "sku": inv_line.sku,
                })

        # PO lines never matched
        for po_idx, po_line in enumerate(po_lines):
            if po_idx not in used_po_indices:
                unmatched_po.append({
                    "index": po_idx,
                    "description": po_line.description,
                    "sku": po_line.sku,
                })

        # Overall status
        mismatches = [m for m in matched_items if m.status != "MATCHED"]
        if mismatches or unmatched_invoice or unmatched_po:
            overall = "FAIL" if mismatches else "WARNING"
            explanation = "; ".join(
                m.explanation for m in mismatches if m.explanation
            ) or f"{len(unmatched_invoice)} unexpected invoice items, {len(unmatched_po)} missing PO items"
        else:
            overall = "PASS"
            explanation = f"All {len(matched_items)} line items match"

        return LineItemValidationResult(
            check_name="Line-item validation",
            status=overall,
            matched_items=matched_items,
            unmatched_invoice_items=unmatched_invoice,
            unmatched_po_items=unmatched_po,
            explanation=explanation,
        )
    finally:
        db.close()
