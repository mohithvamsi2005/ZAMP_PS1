"""Pins the *documented* financial tolerance policy for deployment.

Decision (approved by owner, Phase 9 §3): the enforced rule is
  * absolute balance tolerance: ₹100.00 (PO_AMOUNT_TOLERANCE_ABSOLUTE)
  * rounding band: ₹0.01 (MONEY_ROUNDING_TOLERANCE)
  * the percentage constants (PO_AMOUNT_TOLERANCE_PERCENT, and the
    QUANTITY/UNIT_PRICE '1%' comments) are documented-but-not-enforced —
    the enforced unit comparisons intentionally use raw basis-point
    arithmetic. Do not "fix" this into a percentage rule without a policy
    approval and a versioned policy bump.
"""
import uuid
from decimal import Decimal
from datetime import datetime, timezone

from app.db.models import (
    Invoice, PurchaseOrder, PurchaseOrderLine, Vendor, POStatus, ProcessingRun,
)
from app.db.session import SessionLocal
from app.services.amount_validator import (
    PO_AMOUNT_TOLERANCE_ABSOLUTE,
    PO_AMOUNT_TOLERANCE_PERCENT,
    MONEY_ROUNDING_TOLERANCE,
    validate_amount,
)
from app.services.line_item_validator import (
    QUANTITY_TOLERANCE_PERCENT,
    UNIT_PRICE_TOLERANCE_PERCENT,
    _decimal_close,
)
from app.services.tax_validator import ARITHMETIC_TOLERANCE


class TestPercentConstantsAreInformationalOnly:
    def test_percent_placeholders_keep_their_documented_values(self):
        # These values ship in API output for observability only. Changing
        # them here without policy approval breaks the informational schema.
        assert PO_AMOUNT_TOLERANCE_PERCENT == Decimal("1.0")
        assert QUANTITY_TOLERANCE_PERCENT == Decimal("0.01")
        assert UNIT_PRICE_TOLERANCE_PERCENT == Decimal("0.01")
        assert ARITHMETIC_TOLERANCE == Decimal("0.01")
        assert MONEY_ROUNDING_TOLERANCE == Decimal("0.01")
        assert PO_AMOUNT_TOLERANCE_ABSOLUTE == Decimal("100.00")

    def test_quantity_tolerance_is_hundredx_stricter_than_a_real_percent(self):
        # 0.01 unit == 0.01% (one basis point); a true 1% drift must fail.
        assert _decimal_close(Decimal("100"), Decimal("101"), QUANTITY_TOLERANCE_PERCENT) is False
        assert _decimal_close(Decimal("100"), Decimal("100.0009"), QUANTITY_TOLERANCE_PERCENT) is True


def _mk_po(total: str):
    session = SessionLocal()
    try:
        v = Vendor(
            vendor_code=f"V-TOL-{uuid.uuid4().hex[:6]}",
            legal_name="Tolerance Test Vendor",
            normalized_name="tolerance test vendor",
            status="ACTIVE",
        )
        session.add(v)
        session.flush()
        po = PurchaseOrder(
            po_number=f"PO-TOL-{uuid.uuid4().hex[:6]}",
            vendor_id=v.id,
            issue_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
            currency="INR",
            total_amount=Decimal(total),
            status=POStatus.OPEN,
        )
        session.add(po)
        session.commit()
        return po.id
    finally:
        session.close()


class TestAbsoluteBandEnforcement:
    """The ₹100 band is the deployed contract."""

    def test_one_paisa_over_passes(self):
        po_id = _mk_po("50000.00")
        r = validate_amount(Decimal("50000.01"), po_id=po_id, currency="INR")
        assert r.status == "PASS"

    def test_two_paise_over_is_warning(self):
        po_id = _mk_po("50000.00")
        r = validate_amount(Decimal("50000.02"), po_id=po_id, currency="INR")
        assert r.status == "WARNING"

    def test_full_absolute_band_is_warning(self):
        po_id = _mk_po("50000.00")
        r = validate_amount(Decimal("50000.00") + PO_AMOUNT_TOLERANCE_ABSOLUTE,
                            po_id=po_id, currency="INR")
        assert r.status == "WARNING"

    def test_one_paisa_beyond_band_fails(self):
        po_id = _mk_po("50000.00")
        r = validate_amount(Decimal("50000.00") + PO_AMOUNT_TOLERANCE_ABSOLUTE + Decimal("0.01"),
                            po_id=po_id, currency="INR")
        assert r.status == "FAIL"
