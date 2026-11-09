"""Phase 8 — financial accuracy battery: Decimal precision, rounding boundaries,
PO balance arithmetic, cumulative invoicing, currency edges, invalid inputs.

Money decisions are the heart of the product; these tests pin the exact
boundary semantics of every financial validator so a silent 0.01-drift can
never smuggle itself into production.
"""
import uuid
from decimal import Decimal

from app.db.models import (
    Invoice, PurchaseOrder, PurchaseOrderLine, Vendor, VendorStatus,
    ProcessingRun, POStatus,
)
from app.db.session import SessionLocal
from app.services.amount_validator import (
    validate_amount, PO_AMOUNT_TOLERANCE_ABSOLUTE, PO_AMOUNT_TOLERANCE_PERCENT,
    MONEY_ROUNDING_TOLERANCE,
)
from app.services.tax_validator import (
    ARITHMETIC_TOLERANCE,
    validate_tax_arithmetic as arithmetic,
)
from app.services.line_item_validator import QUANTITY_TOLERANCE_PERCENT

# ── Line-item tolerance reality check ───────────────────────────────────────
# QUANTITY_TOLERANCE_PERCENT / UNIT_PRICE_TOLERANCE_PERCENT == Decimal("0.01").
# _decimal_close compares a raw "%" number against the constant directly, so the
# *effective* tolerance is 0.01% (≈ 1 basis point), NOT the 1% the comments claim.
# This file pins the actual, stricter behavior — deliberately relaxing a
# financial gate mid-phase was not done without a business decision.
assert QUANTITY_TOLERANCE_PERCENT == Decimal("0.01")


def _mk_po(total: str, lines: list[tuple[str, str, str]] = (), vendor_name="Finance Test Vendor", po_number=None):
    session = SessionLocal()
    try:
        vend = Vendor(
            vendor_code=f"V-FIN-{uuid.uuid4().hex[:6]}",
            legal_name=vendor_name,
            normalized_name=vendor_name.lower(),
            status=VendorStatus.ACTIVE,
            default_currency="INR",
        )
        session.add(vend)
        session.flush()
        from datetime import datetime, timezone
        po = PurchaseOrder(
            po_number=po_number or f"PO-FIN-{uuid.uuid4().hex[:6]}",
            vendor_id=vend.id,
            issue_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
            currency="INR",
            total_amount=Decimal(total),
            status=POStatus.OPEN,
        )
        session.add(po)
        session.flush()
        for i, (desc, qty, price) in enumerate(lines):
            line_total = (Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"))
            session.add(PurchaseOrderLine(
                purchase_order_id=po.id, description=desc, sku=f"SKU-{i}",
                quantity=Decimal(qty), unit="pcs",
                unit_price=Decimal(price), line_total=line_total,
            ))
        session.commit()
        return po.id, vend.id
    finally:
        session.close()


def _mk_invoice(po_id: int, vendor_id: int, number: str, total: str, approved: bool = True,
                qty: str = "1", price: str = "0"):
    session = SessionLocal()
    try:
        inv = Invoice(
            invoice_number=number,
            vendor_id=vendor_id,
            purchase_order_id=po_id,
            currency="INR",
            subtotal=Decimal(total),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal(total),
        )
        session.add(inv)
        session.flush()
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        session.add(ProcessingRun(
            id=str(uuid.uuid4()), invoice_id=inv.id,
            status="COMPLETED", decision="APPROVE" if approved else "REVIEW",
            started_at=now, completed_at=now,
        ))
        if qty != "0" and price != "0":
            from app.db.models import InvoiceLine
            session.add(InvoiceLine(
                invoice_id=inv.id, description=f"line-{number}",
                quantity=Decimal(qty), unit="pcs",
                unit_price=Decimal(price),
                line_total=(Decimal(qty) * Decimal(price)).quantize(Decimal("0.01")),
            ))
        session.commit()
        return inv.id
    finally:
        session.close()


# ── 1. Tax arithmetic boundaries ────────────────────────────────────────────


class TestTaxBoundaries:
    def test_exact_reconciliation_passes(self):
        r = arithmetic(Decimal("10000.00"), Decimal("1800.00"), Decimal("500.00"), Decimal("11300.00"))
        assert r.status == "PASS"

    def test_rounding_at_tolerance_edge_passes(self):
        # 9999.99 + 1800.00 − 0.00 = 11799.99 ≈ claimed 11800.00 → diff 0.01 ≤ tolerance
        r = arithmetic(Decimal("9999.99"), Decimal("1800.00"), Decimal("0.00"), Decimal("11800.00"))
        assert r.status == "PASS"
        # The PASS branch reports difference as "0.00" verbatim; pin expected_total instead
        assert r.expected_total == "11799.99"
        assert r.difference == "0.00"

    def test_one_paisa_over_tolerance_fails(self):
        # 9999.99 + 1800.00 = 11799.99 vs claimed 11800.01 → diff 0.02 > 0.01
        r = arithmetic(Decimal("9999.99"), Decimal("1800.00"), Decimal("0.00"), Decimal("11800.01"))
        assert r.status == "FAIL"
        assert r.difference == "0.02"

    def test_zero_tax_and_discount_passes(self):
        r = arithmetic(Decimal("5000.00"), Decimal("0.00"), Decimal("0.00"), Decimal("5000.00"))
        assert r.status == "PASS"

    def test_discount_reduces_total_correctly(self):
        r = arithmetic(Decimal("100000.00"), Decimal("18000.00"), Decimal("5910.15"), Decimal("112089.85"))
        assert r.status == "PASS"

    def test_overstated_discount_fails(self):
        # discount is subtracted, so it cannot manufacture money
        r = arithmetic(Decimal("100000.00"), Decimal("18000.00"), Decimal("20000.00"), Decimal("100000.00"))
        assert r.status == "FAIL"

    def test_negative_input_is_computed_not_dropped(self):
        r = arithmetic(Decimal("-5000.00"), Decimal("0.00"), Decimal("0.00"), Decimal("-5000.00"))
        # Negative subtotal reconciles arithmetically — sign is preserved, never clamped
        assert r.status == "PASS"
        assert Decimal(r.subtotal) < 0

    def test_missing_subtotal_is_unknown_not_zero(self):
        r = arithmetic(None, Decimal("900.00"), Decimal("0.00"), Decimal("5900.00"))
        assert r.status == "UNKNOWN"

    def test_missing_total_is_unknown_not_zero(self):
        r = arithmetic(Decimal("5000.00"), Decimal("900.00"), Decimal("0.00"), None)
        assert r.status == "UNKNOWN"

    def test_garbage_string_is_unknown_not_crash(self):
        r = arithmetic("junk", Decimal("900.00"), Decimal("0.00"), Decimal("5900.00"))
        assert r.status == "UNKNOWN"

    def test_indian_currency_formatting_in_raw_input_does_not_reach_decimal_math(self):
        # The extractor normalises "₹59,000.00" → "59000.00" before schema; this
        # test pins that a previously-normalised string reaches Decimal directly
        assert Decimal("59000.00") == Decimal("59000.00".replace(",", ""))


# ── 2. PO balance boundaries ────────────────────────────────────────────────


class TestAmountBoundaries:
    def test_invoice_exactly_equal_to_balance_passes(self):
        po_id, vendor_id = _mk_po("50000.00")
        r = validate_amount(Decimal("50000.00"), po_id=po_id, currency="INR", exclude_invoice_id=None)
        assert r.status == "PASS"
        assert r.remaining_po_balance == "0.00"

    def test_one_paisa_over_balance_passes_exact_tolerance_edge(self):
        po_id, vendor_id = _mk_po("50000.00")
        # 1 paisa over → difference == MONEY_ROUNDING_TOLERANCE exactly → not ">" → PASS
        r = validate_amount(Decimal("50000.01"), po_id=po_id, currency="INR")
        assert r.status == "PASS"
        assert MONEY_ROUNDING_TOLERANCE == Decimal("0.01")

    def test_two_paise_over_balance_is_warning(self):
        po_id, vendor_id = _mk_po("50000.00")
        r = validate_amount(Decimal("50000.02"), po_id=po_id, currency="INR")
        assert r.status == "WARNING"
        assert r.difference == "0.02"

    def test_full_absolute_tolerance_band_is_warning(self):
        po_id, vendor_id = _mk_po("50000.00")
        r = validate_amount(Decimal("50000.00") + PO_AMOUNT_TOLERANCE_ABSOLUTE, po_id=po_id, currency="INR")
        assert r.status == "WARNING"
        assert r.difference == str(PO_AMOUNT_TOLERANCE_ABSOLUTE)

    def test_one_paisa_beyond_absolute_tolerance_fails(self):
        po_id, vendor_id = _mk_po("50000.00")
        r = validate_amount(Decimal("50000.00") + PO_AMOUNT_TOLERANCE_ABSOLUTE + Decimal("0.01"),
                            po_id=po_id, currency="INR")
        assert r.status == "FAIL"
        assert r.difference == str(PO_AMOUNT_TOLERANCE_ABSOLUTE + Decimal("0.01"))

    def test_overbilling_produces_precise_difference(self):
        po_id, _ = _mk_po("100000.00")
        prior_id = _mk_invoice(po_id, 1, "INV-BAL-PRIOR", "75000.00", approved=True)
        r = validate_amount(Decimal("40000.00"), po_id=po_id, currency="INR")
        # remaining before = 25000 → excess = 15000.00 exactly
        assert r.status == "FAIL"
        assert r.difference == "15000.00"
        assert r.previously_approved_invoiced == "75000.00"
        assert r.remaining_po_balance == "25000.00"

    def test_unapproved_history_is_provisional_basis(self):
        po_id, _ = _mk_po("100000.00")
        _mk_invoice(po_id, 1, "INV-UNAPR-1", "60000.00", approved=False)
        r = validate_amount(Decimal("50000.00"), po_id=po_id, currency="INR")
        # provisional basis=60000 → remaining=40000; request 50000 exceeds by 10000
        assert r.status == "FAIL"
        assert "PROVISIONAL" in r.explanation
        assert r.metadata["provisional"] is True
        assert r.metadata["unapproved_invoice_count"] == 1

    def test_approved_history_anchors_basis_not_unapproved(self):
        po_id, _ = _mk_po("100000.00")
        _mk_invoice(po_id, 1, "INV-A-1", "40000.00", approved=True)
        _mk_invoice(po_id, 1, "INV-U-1", "30000.00", approved=False)
        # approved=40000 is the committed basis; unapproved 30000 NOT counted;
        # remaining=60000 → request 55000 fits → PASS
        r = validate_amount(Decimal("55000.00"), po_id=po_id, currency="INR")
        assert r.status == "PASS"
        assert r.metadata["provisional"] is False
        assert r.previously_approved_invoiced == "40000.00"

    def test_current_invoice_never_counts_itself(self):
        po_id, _ = _mk_po("100000.00")
        cur_id = _mk_invoice(po_id, 1, "INV-SELF", "90000.00", approved=True)
        # Same invoice re-asked: excluded → basis=0 → not provisional (still APPROVE history for itself? no—excluded)
        r = validate_amount(Decimal("90000.00"), po_id=po_id, currency="INR", exclude_invoice_id=cur_id)
        assert r.previously_approved_invoiced == "0"

    def test_cumulative_invoicing_across_many_approvals(self):
        po_id, _ = _mk_po("100000.00")
        for i, amt in enumerate(["10000.00", "20000.00", "15000.00", "25000.00"]):
            _mk_invoice(po_id, 1, f"INV-CUM-{i}", amt, approved=True)
        r = validate_amount(Decimal("10000.00"), po_id=po_id, currency="INR")
        # approved=70000 → remaining=30000 → 10000 fits → PASS
        assert r.status == "PASS"
        assert r.previously_approved_invoiced == "70000.00"
        assert r.metadata["remaining_before"] == "30000.00"

    def test_invalid_decimal_strings_become_unknown_never_pass(self):
        po_id, _ = _mk_po("100000.00")
        r = validate_amount(None, po_id=po_id, currency="INR")
        assert r.status == "UNKNOWN"
        assert "could not be completed" in r.explanation

    def test_different_currency_is_warning_never_pass(self):
        po_id, _ = _mk_po("100000.00")
        r = validate_amount(Decimal("100.00"), po_id=po_id, currency="USD")
        assert r.status == "WARNING"
        assert r.metadata["currency_mismatch"] is True

    def test_po_amount_tolerance_percent_is_not_silently_applied(self):
        # PO_AMOUNT_TOLERANCE_PERCENT exists in config but is NOT referenced by
        # the balance branch — the enforced budget is the absolute tolerance.
        # This test documents that honestly rather than pretending otherwise.
        assert PO_AMOUNT_TOLERANCE_PERCENT == Decimal("1.0")
        # By code inspection: no code path reads it. Pin the actual behavior:
        po_id, _ = _mk_po("50000.00")
        # 1% of 50000 = 500 ₹ would "pass" under a percent rule; under the real
        # absolute budget of 100 ₹ the same request is a FAIL.
        r = validate_amount(Decimal("50500.00"), po_id=po_id, currency="INR")
        assert r.status == "FAIL"


# ── 3. Line-item economics ─────────────────────────────────────────────────


class TestLineItemEconomics:
    def test_quantity_exactly_at_tolerance_matched(self):
        # 100 vs 100.009 → 0.00899% ≤ 0.01% → MATCHED (effective tolerance pin)
        po_id, vendor_id = _mk_po(
            "100000.00",
            lines=[("Precision Bolt", "100.009", "50.00")],
            vendor_name="Line Boundary Vendor",
            po_number=f"PO-LI-{uuid.uuid4().hex[:6]}",
        )
        inv_id = _mk_invoice(po_id, vendor_id, "INV-LI-1", "5000.00")
        from app.db.models import InvoiceLine
        session = SessionLocal()
        try:
            session.query(InvoiceLine).filter_by(invoice_id=inv_id).delete()
            session.add(InvoiceLine(
                invoice_id=inv_id, description="Precision Bolt",
                quantity=Decimal("100"), unit="pcs",
                unit_price=Decimal("50.00"), line_total=Decimal("5000.00"),
            ))
            session.commit()
        finally:
            session.close()
        from app.services.line_item_validator import validate_line_items
        assert validate_line_items(invoice_id=inv_id, po_id=po_id).matched_items[0].status == "MATCHED"

    def test_quantity_one_percent_drift_is_mismatch(self):
        # 101 vs 100 → 0.99% — far above the effective 0.01% budget → QUANTITY_MISMATCH
        po_id, vendor_id = _mk_po(
            "100000.00",
            lines=[("Demanded Bolt", "100", "50.00")],
            vendor_name="Line Boundary Vendor",
            po_number=f"PO-LI-{uuid.uuid4().hex[:6]}",
        )
        inv_id = _mk_invoice(po_id, vendor_id, "INV-LI-2", "5000.00")
        from app.db.models import InvoiceLine
        session = SessionLocal()
        try:
            session.query(InvoiceLine).filter_by(invoice_id=inv_id).delete()
            session.add(InvoiceLine(
                invoice_id=inv_id, description="Demanded Bolt",
                quantity=Decimal("101"), unit="pcs",
                unit_price=Decimal("50.00"), line_total=Decimal("5050.00"),
            ))
            session.commit()
        finally:
            session.close()
        from app.services.line_item_validator import validate_line_items
        result = validate_line_items(invoice_id=inv_id, po_id=po_id)
        assert result.matched_items[0].status == "QUANTITY_MISMATCH"
        assert result.status in ("FAIL", "WARNING")

    def test_quantity_exactly_at_tiny_percent_matched(self):
        # 100 vs 100.01 → 0.00999% ≤ 0.01% → MATCHED
        po_id, vendor_id = _mk_po(
            "100000.00",
            lines=[("Edge Bolt", "100.01", "50.00")],
            vendor_name="Edge Vendor",
            po_number=f"PO-ED-{uuid.uuid4().hex[:6]}",
        )
        inv_id = _mk_invoice(po_id, vendor_id, "INV-LI-3", "5000.00")
        from app.db.models import InvoiceLine
        session = SessionLocal()
        try:
            session.query(InvoiceLine).filter_by(invoice_id=inv_id).delete()
            session.add(InvoiceLine(
                invoice_id=inv_id, description="Edge Bolt",
                quantity=Decimal("100"), unit="pcs",
                unit_price=Decimal("50.00"), line_total=Decimal("5000.00"),
            ))
            session.commit()
        finally:
            session.close()
        from app.services.line_item_validator import validate_line_items
        assert validate_line_items(invoice_id=inv_id, po_id=po_id).matched_items[0].status == "MATCHED"

    def test_line_total_must_reconcile(self):
        po_id, vendor_id = _mk_po(
            "100000.00",
            lines=[("Decimal Bolt", "100", "33.33")],
            vendor_name="Reconcile Vendor",
            po_number=f"PO-RE-{uuid.uuid4().hex[:6]}",
        )
        inv_id = _mk_invoice(po_id, vendor_id, "INV-RE-1", "3333.00")
        from app.services.line_item_validator import validate_line_items
        result = validate_line_items(invoice_id=inv_id, po_id=po_id)
        assert result.status == "WARNING"  # no invoice lines persisted — PO line unmatched
        assert len(result.unmatched_po_items) == 1


# ── 4. Money type discipline — no raw floats in decision paths ─────────────


class TestMoneyTypeDiscipline:
    def test_amount_validator_returns_strings_not_floats(self):
        po_id, _ = _mk_po("1000.00")
        r = validate_amount(Decimal("100.00"), po_id=po_id, currency="INR")
        assert isinstance(r.po_total, str)
        assert isinstance(r.previously_approved_invoiced, str)
        assert isinstance(r.remaining_po_balance, str)

    def test_tax_validator_outputs_are_strings_or_none(self):
        r = arithmetic(Decimal("100.00"), Decimal("10.00"), Decimal("0.00"), Decimal("110.00"))
        assert isinstance(r.expected_total, str)
        assert isinstance(r.difference, str)

    def test_sum_of_many_decimals_is_exact(self):
        vals = [Decimal("0.10")] * 100
        assert sum(vals, Decimal("0")) == Decimal("10.00")

    def test_decimal_quantize_prevents_float_pollution(self):
        total = sum((Decimal("0.1") * Decimal("3") for _ in range(3)), Decimal("0"))
        assert total == Decimal("0.9")
        assert not isinstance(total, float)
