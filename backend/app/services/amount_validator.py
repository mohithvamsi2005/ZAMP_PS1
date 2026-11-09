"""Amount validation using Decimal — PO balance, split invoices, provisional balances, tolerances.

Committed-amount rules (see PS-1 plan §7 "PO cumulative billing" and Phase 6 §8):

* Only invoices with a completed APPROVE processing run contribute committed amounts.
* REVIEW / REJECT / FAILED invoices are NOT treated as approved commitments.
* The invoice currently being processed (exclude_invoice_id) is excluded from every
  query so it cannot be double-counted.
* When no APPROVE history exists but other invoices target the same PO, the committed
  amount is unknown: the balance basis falls back to those unapproved amounts and the
  result is flagged provisional (status WARNING) so it can never silently approve.
* SQLite limitation: reads happen in a single short transaction; there is no row
  lock. Two concurrent uploads against the same PO could both read the same
  remaining balance before either commits an APPROVE run — a documented MVP
  race condition (dev deployments process uploads sequentially).
"""
from decimal import Decimal
from typing import Optional

from app.db.models import PurchaseOrder, Invoice, ProcessingRun
from app.db.session import SessionLocal
from app.schemas.matching import AmountValidationResult


# Configurable tolerances
MONEY_ROUNDING_TOLERANCE = Decimal("0.01")
PO_AMOUNT_TOLERANCE_PERCENT = Decimal("1.0")   # 1%
PO_AMOUNT_TOLERANCE_ABSOLUTE = Decimal("100.00")


def _sum_invoices(rows) -> Decimal:
    total = Decimal("0")
    for amount in rows:
        if amount is not None:
            total += Decimal(str(amount))
    return total


def _approved_invoiced(po_id: int, db_session, exclude_invoice_id: Optional[int]) -> Decimal:
    """Sum totals of invoices linked to this PO that have an APPROVE run.

    Sums invoice rows, not run rows, so a retried run chain cannot double-count
    a single invoice. Excludes the invoice currently being processed.
    """
    approved_ids = {
        row[0]
        for row in (
            db_session.query(ProcessingRun.invoice_id)
            .filter(ProcessingRun.decision == "APPROVE")
            .all()
        )
        if row[0] is not None
    }
    if not approved_ids:
        return Decimal("0")

    query = (
        db_session.query(Invoice.total_amount)
        .filter(
            Invoice.purchase_order_id == po_id,
            Invoice.id.in_(approved_ids),
        )
    )
    if exclude_invoice_id is not None:
        query = query.filter(Invoice.id != exclude_invoice_id)
    return _sum_invoices([row[0] for row in query.all()])


def _unapproved_invoiced_reference(po_id: int, db_session, exclude_invoice_id: Optional[int]):
    """Return (count, sum) of other invoices on this PO without an approved run.

    Informational only — these amounts are NOT treated as committed, but they
    make the balance basis provisional when no approved history exists.
    """
    approved_ids = {
        row[0]
        for row in (
            db_session.query(ProcessingRun.invoice_id)
            .filter(ProcessingRun.decision == "APPROVE")
            .all()
        )
        if row[0] is not None
    }
    query = db_session.query(Invoice).filter(Invoice.purchase_order_id == po_id)
    if exclude_invoice_id is not None:
        query = query.filter(Invoice.id != exclude_invoice_id)
    if approved_ids:
        query = query.filter(~Invoice.id.in_(approved_ids))
    others = query.all()
    other_sum = _sum_invoices([inv.total_amount for inv in others])
    return len(others), other_sum


def validate_amount(
    invoice_total: Optional[Decimal],
    po_id: Optional[int] = None,
    currency: Optional[str] = None,
    exclude_invoice_id: Optional[int] = None,
) -> AmountValidationResult:
    """Validate invoice amount against the PO balance.

    Rules:
      - If no PO matched → PASS, balance check skipped (nothing to verify against).
      - Previously approved invoices reduce the available balance.
      - Unapproved historical invoices (REVIEW/REJECT/FAILED or never processed)
        are not counted as commitments, but when they are the ONLY history for a
        PO the committed amount is unreliable → provisional WARNING.
      - Different currencies are flagged as WARNING (comparison is provisional).
    """
    db = SessionLocal()
    try:
        result = AmountValidationResult(
            check_name="Amount validation",
            status="PASS",
            invoice_amount=str(invoice_total) if invoice_total is not None else "0",
            tolerance_absolute=str(PO_AMOUNT_TOLERANCE_ABSOLUTE),
            tolerance_percent=float(PO_AMOUNT_TOLERANCE_PERCENT),
        )

        if po_id is None:
            result.explanation = "No PO matched; amount validation skipped against PO balance"
            return result

        po = db.get(PurchaseOrder, po_id)
        if po is None:
            result.status = "FAIL"
            result.explanation = f"PO id={po_id} not found in database"
            return result

        # Currency mismatch check
        if currency and po.currency != currency:
            result.status = "WARNING"
            result.po_total = str(po.total_amount)
            result.metadata = {
                "currency_mismatch": True,
                "invoice_currency": currency,
                "po_currency": po.currency,
            }
            result.explanation = (
                f"Currency mismatch: invoice={currency}, PO={po.currency}. "
                f"Amount comparison is provisional."
            )
            return result

        po_total = Decimal(str(po.total_amount))
        previously_approved = _approved_invoiced(po_id, db, exclude_invoice_id)
        unapproved_count, unapproved_sum = _unapproved_invoiced_reference(
            po_id, db, exclude_invoice_id,
        )

        # Balance basis: approved history is authoritative; otherwise the PO's
        # other unapproved invoices make the committed amount provisional.
        provisional = previously_approved == 0 and unapproved_count > 0
        basis = previously_approved if not provisional else unapproved_sum

        remaining_before = po_total - basis
        if invoice_total is None:
            result.po_total = str(po_total)
            result.previously_approved_invoiced = str(previously_approved)
            result.remaining_po_balance = str(max(remaining_before, Decimal("0")))
            result.status = "UNKNOWN"
            result.metadata = {"provisional": provisional}
            result.explanation = "Invoice total missing; PO balance check could not be completed"
            return result

        remaining_after = remaining_before - invoice_total

        result.po_total = str(po_total)
        result.previously_approved_invoiced = str(previously_approved)
        result.metadata = {
            "provisional": provisional,
            "unapproved_invoiced": str(unapproved_sum) if provisional else "0.00",
            "unapproved_invoice_count": unapproved_count,
            "remaining_before": str(remaining_before),
        }

        if remaining_after < -PO_AMOUNT_TOLERANCE_ABSOLUTE:
            difference = abs(remaining_after)
            result.status = "FAIL"
            result.difference = str(difference)
            result.remaining_po_balance = str(max(remaining_before, Decimal("0")))
            result.explanation = (
                f"Invoice {invoice_total} exceeds remaining PO balance by {difference}. "
                f"PO total={po_total}, committed basis={basis}"
                f"{' (PROVISIONAL)' if provisional else ''}, "
                f"remaining before={remaining_before}"
            )
            return result

        if remaining_after < Decimal("0"):
            difference = abs(remaining_after)
            if difference > MONEY_ROUNDING_TOLERANCE:
                result.status = "WARNING"
                result.difference = str(difference)
                result.remaining_po_balance = str(max(remaining_before, Decimal("0")))
                result.explanation = (
                    f"Invoice exceeds remaining PO balance by {difference} "
                    f"(within tolerance {PO_AMOUNT_TOLERANCE_ABSOLUTE}). "
                    f"PO total={po_total}, committed basis={basis}, "
                    f"remaining before={remaining_before}"
                )
                return result

        if provisional:
            result.remaining_po_balance = str(max(remaining_after, Decimal("0")))
            result.status = "WARNING"
            result.explanation = (
                f"Invoice {invoice_total} fits within the provisional balance "
                f"(remaining after={max(remaining_after, Decimal('0'))}) but no APPROVED "
                f"invoice history exists for this PO; committed amount is unknown "
                f"({unapproved_count} unapproved invoice(s) totalling {unapproved_sum}). "
                f"Requires human confirmation."
            )
            return result

        result.remaining_po_balance = str(max(remaining_after, Decimal("0")))
        result.status = "PASS"
        result.explanation = (
            f"Invoice {invoice_total} within remaining PO balance. "
            f"PO total={po_total}, previously approved={previously_approved}, "
            f"remaining after={max(remaining_after, Decimal('0'))}"
        )
        return result
    finally:
        db.close()
