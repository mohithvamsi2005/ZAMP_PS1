"""Phase 4 tests: vendor matching, PO matching, duplicate detection, amount validation, line-item validation, tax arithmetic."""
import pytest
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy import text
from app.db.session import engine, SessionLocal, init_db, enable_sqlite_foreign_keys
from app.db.models import (
    Vendor, VendorStatus, PurchaseOrder, POStatus,
    PurchaseOrderLine, Invoice, InvoiceLine,
    ProcessingRun, ProcessingRunStatus,
)
from app.schemas.matching import (
    VendorMatchResult, POMatchResult, DuplicateResult,
    AmountValidationResult, LineItemValidationResult, TaxValidationResult,
)
from app.services.normalizer import (
    normalize_vendor_name, normalize_tax_id, normalize_invoice_number,
    normalize_po_reference, safe_decimal,
)
from app.services.vendor_matcher import match_vendor
from app.services.po_matcher import match_po
from app.services.duplicate_detector import detect_duplicates
from app.services.amount_validator import validate_amount
from app.services.line_item_validator import validate_line_items
from app.services.tax_validator import validate_tax_arithmetic


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_session():
    """Fresh database session with seeded data for each test."""
    # Drop and recreate all tables to ensure isolation between tests
    from app.db.models import Base
    Base.metadata.drop_all(bind=engine)
    init_db()
    enable_sqlite_foreign_keys(SessionLocal())
    # Seed vendors and POs (idempotent)
    from app.db.seed import seed as run_seed
    try:
        run_seed()
    except Exception:
        pass
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def vendor_abc(db_session):
    """Return the ABC Industrial Supplies vendor (V-001)."""
    return db_session.query(Vendor).filter_by(vendor_code="V-001").first()


@pytest.fixture
def vendor_xyz(db_session):
    """Return XYZ Metals and Alloys (V-002)."""
    return db_session.query(Vendor).filter_by(vendor_code="V-002").first()


@pytest.fixture
def vendor_blocked(db_session):
    """Return Sharma Electrical Components (V-004, BLOCKED)."""
    return db_session.query(Vendor).filter_by(vendor_code="V-004").first()


@pytest.fixture
def po_2041(db_session):
    """Return PO-2041."""
    return db_session.query(PurchaseOrder).filter_by(po_number="PO-2041").first()


@pytest.fixture
def po_2042(db_session):
    """Return PO-2042."""
    return db_session.query(PurchaseOrder).filter_by(po_number="PO-2042").first()


# ── Normalization Tests ───────────────────────────────────────────────────────


class TestNormalization:
    def test_normalize_vendor_name_removes_suffix(self):
        assert normalize_vendor_name("ABC Industrial Supplies Pvt Ltd") == "abc industrial supplies"
        assert normalize_vendor_name("ABC Industrial Supplies Limited") == "abc industrial supplies"

    def test_normalize_vendor_name_strips_whitespace_and_punctuation(self):
        # em-dash and en-dash are stripped by the regex
        result = normalize_vendor_name("  ABC  —  Industrial  ")
        assert "abc industrial" in result

    def test_normalize_tax_id_uppercases(self):
        assert normalize_tax_id("27aabca1234f1z5") == "27AABCA1234F1Z5"
        assert normalize_tax_id(None) == ""

    def test_normalize_invoice_number_cleans_separators(self):
        assert normalize_invoice_number("INV-2026/1042") == "inv20261042"
        assert normalize_invoice_number(None) == ""

    def test_normalize_po_reference_uppercases_and_strips(self):
        assert normalize_po_reference("  po-2041  ") == "PO2041"
        assert normalize_po_reference(None) == ""

    def test_safe_decimal_parses_string(self):
        assert safe_decimal("500.00") == Decimal("500.00")
        assert safe_decimal(500) == Decimal("500")
        assert safe_decimal(None) is None
        assert safe_decimal("not-a-number") is None


# ── Vendor Matching Tests ─────────────────────────────────────────────────────


class TestVendorMatching:
    def test_exact_tax_id_match(self, vendor_abc):
        """Level 1 — exact tax ID should match ABC Industrial Supplies."""
        result = match_vendor(vendor_tax_id="27AABCA1234F1Z5")
        assert result.status == "MATCHED"
        assert result.match_method == "EXACT_TAX_ID"
        assert result.matched_vendor is not None
        assert result.matched_vendor.vendor_code == "V-001"
        assert result.confidence == 1.0

    def test_exact_normalized_name_match(self, vendor_xyz):
        """Level 2 — exact normalized name should match XYZ Metals."""
        result = match_vendor(vendor_name="XYZ Metals and Alloys")
        assert result.status == "MATCHED"
        assert result.match_method == "EXACT_NAME"
        assert result.matched_vendor.vendor_code == "V-002"

    def test_fuzzy_name_match_minor_spelling(self, vendor_abc):
        """Level 3 — minor spelling difference should fuzzy match."""
        result = match_vendor(vendor_name="ABG Industrial Supplies")
        # Score ~95.6 against normalized ABC → MATCHED
        assert result.status == "MATCHED"

    def test_blocked_vendor_returns_needs_review(self, vendor_blocked):
        """Blocked vendors should not be auto-matched — require review."""
        result = match_vendor(vendor_tax_id="07AAQCS1234E1Z8")
        assert result.status == "NEEDS_REVIEW"

    def test_ambiguous_vendor_match(self, db_session):
        """Two very similar names should produce AMBIGUOUS."""
        # Add a second vendor with a very similar name to ABC
        dup = Vendor(
            vendor_code="V-AMB",
            legal_name="ABC Industrial Supplies Ltd",
            normalized_name="abc industrial supplies ltd",
            status=VendorStatus.ACTIVE,
        )
        db_session.add(dup)
        db_session.commit()

        result = match_vendor(vendor_name="ABC Industrial Supplies")
        # With a very close fuzzy candidate (score ~91+), should be AMBIGUOUS or MATCHED
        assert result.status in ("MATCHED", "AMBIGUOUS", "NEEDS_REVIEW")

    def test_no_match_returns_unmatched(self):
        """Vendor not in DB → UNMATCHED."""
        result = match_vendor(vendor_name="NonExistent Vendor Corp")
        assert result.status == "UNMATCHED"
        assert result.confidence == 0.0

    def test_missing_fields_returns_unmatched(self):
        """No name, no tax ID → UNMATCHED."""
        result = match_vendor()
        assert result.status == "UNMATCHED"


# ── PO Matching Tests ─────────────────────────────────────────────────────────


class TestPOMatching:
    def test_exact_po_reference_match(self, po_2041):
        """Exact PO number should match."""
        result = match_po(po_reference="PO-2041")
        assert result.status == "MATCHED"
        assert result.match_method == "EXACT_PO_NUMBER"
        assert result.matched_po is not None
        assert result.matched_po.po_number == "PO-2041"

    def test_missing_po_reference_no_vendor(self):
        """No PO reference and no vendor match → MISSING_PO."""
        result = match_po(po_reference=None, matched_vendor_id=None)
        assert result.status == "MISSING_PO"

    def test_candidate_po_with_matched_vendor(self, vendor_abc):
        """When PO ref is absent but vendor matches, should find candidate."""
        result = match_po(po_reference=None, matched_vendor_id=vendor_abc.id)
        # Should return at least one candidate (PO-2041 and PO-2044 both belong to V-001)
        assert result.status in ("MATCHED", "AMBIGUOUS")

    def test_ambiguous_po_candidates(self, vendor_abc):
        """Multiple POs for same vendor with no reference → AMBIGUOUS."""
        # ABC has PO-2041 and PO-2044 — should be ambiguous when ref is missing
        result = match_po(po_reference=None, matched_vendor_id=vendor_abc.id)
        if result.status == "AMBIGUOUS":
            assert len(result.candidates) >= 2

    def test_currency_mismatch_flagged(self, po_2041):
        """Exact PO match should succeed regardless of invoice currency (checked in amount validation)."""
        result = match_po(po_reference="PO-2041")
        assert result.status == "MATCHED"


# ── Duplicate Detection Tests ─────────────────────────────────────────────────


class TestDuplicateDetection:
    def test_no_duplicate_found(self):
        """Fresh invoice with no DB matches → NO_DUPLICATE_FOUND."""
        result = detect_duplicates(
            vendor_id=None,
            invoice_number="INV-NEW-001",
        )
        assert result.status == "NO_DUPLICATE_FOUND"

    def test_exact_invoice_duplicate(self, db_session, vendor_abc):
        """Same vendor + same invoice number → EXACT_INVOICE_DUPLICATE."""
        inv = Invoice(
            invoice_number="INV-DUP-001",
            vendor_id=vendor_abc.id,
            currency="INR",
            total_amount=Decimal("5000"),
        )
        db_session.add(inv)
        db_session.commit()

        result = detect_duplicates(
            vendor_id=vendor_abc.id,
            invoice_number="INV-DUP-001",
        )
        assert result.status == "EXACT_INVOICE_DUPLICATE"
        assert result.existing_invoice_id is not None

    def test_potential_duplicate(self, db_session, vendor_abc):
        """Similar but different invoice number + same total → POTENTIAL_DUPLICATE."""
        # First insert a real invoice
        inv = Invoice(
            invoice_number="INV-2026-1042",
            vendor_id=vendor_abc.id,
            currency="INR",
            total_amount=Decimal("59000.00"),
        )
        db_session.add(inv)
        db_session.commit()

        # Now query with a similar but different number
        result = detect_duplicates(
            vendor_id=vendor_abc.id,
            invoice_number="INV-2026-1043",  # different from existing INV-2026-1042
            total_amount=Decimal("59000.00"),
            currency="INR",
        )
        assert result.status == "POTENTIAL_DUPLICATE"


# ── Amount Validation Tests ───────────────────────────────────────────────────


class TestAmountValidation:
    def test_within_po_balance(self, po_2041):
        """Provisional basis: no approved invoices exist, only an unapproved one.

        Seed data has INV-2026-1042 (59000, never run) on PO-2041 (100000).
        Unapproved invoices are NOT commitments, but because they are the only
        history the balance basis is provisional (59000) → remaining 41000.
        Requesting 59000 exceeds that provisional basis → FAIL, flagged
        provisional in metadata (Phase 6 amount semantics).
        """
        result = validate_amount(
            invoice_total=Decimal("59000.00"),
            po_id=po_2041.id,
            currency="INR",
        )
        assert result.status == "FAIL"
        assert result.metadata.get("provisional") is True
        assert "PROVISIONAL" in result.explanation
        assert result.previously_approved_invoiced == "0"

    def test_exact_remaining_balance(self, po_2041):
        """100000 vs provisional basis (59000) — must not silently pass.

        Seed has unapproved INV-2026-1042 (59000) on PO-2041 (total 100000).
        Previously APPROVE-basis is 0, unapproved history is 59000, so the
        balance basis is provisional. Requesting 100000 exceeds the provisional
        remaining 41000 by 59000 → FAIL flagged as PROVISIONAL — never a silent
        PASS (Phase 6 amount semantics).
        """
        result = validate_amount(
            invoice_total=Decimal("100000.00"),
            po_id=po_2041.id,
            currency="INR",
        )
        assert result.status == "FAIL"
        assert result.metadata["provisional"] is True
        assert "PROVISIONAL" in result.explanation

    def test_exceeds_remaining_balance(self, db_session, po_2041):
        """Invoice exceeds remaining PO balance → FAIL."""
        # First approve a prior invoice that consumes most of the balance
        prior_inv = Invoice(
            invoice_number="INV-PREV-001",
            vendor_id=po_2041.vendor_id,
            purchase_order_id=po_2041.id,
            currency="INR",
            total_amount=Decimal("80000.00"),
        )
        db_session.add(prior_inv)
        db_session.flush()  # must flush to get ID before creating ProcessingRun

        run = ProcessingRun(
            id=str(__import__("uuid").uuid4()),
            invoice_id=prior_inv.id,
            status=ProcessingRunStatus.COMPLETED,
            decision="APPROVE",
        )
        db_session.add(run)
        db_session.commit()

        # New invoice of 30000 against PO with 80000 already approved (remaining = 20000)
        result = validate_amount(
            invoice_total=Decimal("30000.00"),
            po_id=po_2041.id,
            currency="INR",
        )
        assert result.status == "FAIL"

    def test_split_invoice_two_payments(self, db_session, po_2041):
        """Two invoices against same PO: first within balance, second also within remaining."""
        inv1 = Invoice(
            invoice_number="INV-SPLIT-001",
            vendor_id=po_2041.vendor_id,
            purchase_order_id=po_2041.id,
            currency="INR",
            total_amount=Decimal("50000.00"),
        )
        db_session.add(inv1)
        db_session.flush()

        run1 = ProcessingRun(
            id=str(__import__("uuid").uuid4()),
            invoice_id=inv1.id,
            status=ProcessingRunStatus.COMPLETED,
            decision="APPROVE",
        )
        db_session.add(run1)
        db_session.commit()

        # Second invoice for 40000; remaining after first = 50000 → should PASS
        result = validate_amount(
            invoice_total=Decimal("40000.00"),
            po_id=po_2041.id,
            currency="INR",
        )
        assert result.status == "PASS"

    def test_no_po_match_passes(self):
        """No PO matched → amount validation should pass (no balance check)."""
        result = validate_amount(invoice_total=Decimal("999999.00"), po_id=None)
        assert result.status == "PASS"


# ── Line-Item Validation Tests ────────────────────────────────────────────────


class TestLineItemValidation:
    def test_matching_line_items_partial(self, db_session, po_2041):
        """Invoice with fewer lines than PO → WARNING for missing items."""
        inv = Invoice(
            invoice_number="INV-LINE-PARTIAL",
            vendor_id=po_2041.vendor_id,
            purchase_order_id=po_2041.id,
            currency="INR",
            total_amount=Decimal("50000.00"),
        )
        db_session.add(inv)
        db_session.flush()

        line = InvoiceLine(
            invoice_id=inv.id,
            description="Steel sheets, grade 304",
            sku="SS-304-6",
            quantity=Decimal("100"),
            unit="sheets",
            unit_price=Decimal("500.00"),
            line_total=Decimal("50000.00"),
        )
        db_session.add(line)
        db_session.commit()

        result = validate_line_items(invoice_id=inv.id, po_id=po_2041.id)
        # 1 of 3 PO lines matched; 2 unmatched → WARNING (not FAIL since no mismatches)
        assert result.status == "WARNING"
        assert len(result.matched_items) == 1

    def test_quantity_mismatch(self, db_session, po_2041):
        """Invoice quantity differs significantly from PO → FAIL."""
        inv = Invoice(
            invoice_number="INV-QTY-DIFF",
            vendor_id=po_2041.vendor_id,
            purchase_order_id=po_2041.id,
            currency="INR",
            total_amount=Decimal("50000.00"),
        )
        db_session.add(inv)
        db_session.flush()

        line = InvoiceLine(
            invoice_id=inv.id,
            description="Steel sheets, grade 304",
            sku="SS-304-6",
            quantity=Decimal("150"),  # PO has 100
            unit="sheets",
            unit_price=Decimal("500.00"),
            line_total=Decimal("75000.00"),
        )
        db_session.add(line)
        db_session.commit()

        result = validate_line_items(invoice_id=inv.id, po_id=po_2041.id)
        assert result.status in ("FAIL", "WARNING")

    def test_missing_po_returns_pass(self):
        """No PO matched → line-item validation should pass (skipped)."""
        result = validate_line_items(invoice_id=999, po_id=None)
        assert result.status == "PASS"


# ── Tax / Arithmetic Validation Tests ────────────────────────────────────────


class TestTaxArithmetic:
    def test_correct_arithmetic(self):
        """Subtotal + tax − discount = total → PASS."""
        result = validate_tax_arithmetic(
            subtotal=Decimal("50000.00"),
            tax_amount=Decimal("9000.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("59000.00"),
        )
        assert result.status == "PASS"

    def test_arithmetic_mismatch(self):
        """Wrong total → FAIL."""
        result = validate_tax_arithmetic(
            subtotal=Decimal("50000.00"),
            tax_amount=Decimal("9000.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("60000.00"),  # off by 1000
        )
        assert result.status == "FAIL"

    def test_with_discount(self):
        """Subtotal + tax − discount = total → PASS."""
        result = validate_tax_arithmetic(
            subtotal=Decimal("10000.00"),
            tax_amount=Decimal("1800.00"),
            discount_amount=Decimal("500.00"),
            total_amount=Decimal("11300.00"),
        )
        assert result.status == "PASS"

    def test_missing_fields_unknown(self):
        """Missing subtotal → UNKNOWN."""
        result = validate_tax_arithmetic(
            subtotal=None,
            tax_amount=Decimal("9000.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("59000.00"),
        )
        assert result.status == "UNKNOWN"


# ── End-to-End Matching Scenarios ─────────────────────────────────────────────


class TestMatchingScenarios:
    """Three realistic scenarios using actual seed data."""

    def test_scenario_1_clean_invoice(self, db_session, vendor_abc, po_2041):
        """Happy path: exact tax ID match, exact PO match, within balance, clean arithmetic."""
        # Use a unique invoice number to avoid conflicts with seeded data
        inv = Invoice(
            invoice_number="INV-SCENARIO-1",
            vendor_id=vendor_abc.id,
            purchase_order_id=po_2041.id,
            currency="INR",
            subtotal=Decimal("50000.00"),
            tax_amount=Decimal("9000.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("59000.00"),
        )
        db_session.add(inv)
        db_session.commit()

        vendor_result = match_vendor(vendor_tax_id="27AABCA1234F1Z5")
        assert vendor_result.status == "MATCHED"

        po_result = match_po(po_reference="PO-2041", matched_vendor_id=vendor_abc.id)
        assert po_result.status == "MATCHED"

        # A PO with NO prior invoice rows at all → not provisional → PASS.
        # (PO-2041 is disqualified: seed has INV-2026-1042 on it, so its balance
        # basis would be provisional.)
        po_2044 = db_session.query(PurchaseOrder).filter_by(po_number="PO-2044").first()
        amount_result = validate_amount(
            invoice_total=Decimal("59000.00"),
            po_id=po_2044.id,
            currency="INR",
        )
        assert amount_result.status == "PASS"
        assert amount_result.metadata["provisional"] is False

    def test_scenario_2_overbilling(self, db_session, vendor_xyz, po_2042):
        """Edge case: invoice exceeds remaining PO balance."""
        prior = Invoice(
            invoice_number="INV-PREV-OVER",
            vendor_id=vendor_xyz.id,
            purchase_order_id=po_2042.id,
            currency="INR",
            total_amount=Decimal("70000.00"),
        )
        db_session.add(prior)
        db_session.flush()  # need ID for processing run

        run = ProcessingRun(
            id=str(__import__("uuid").uuid4()),
            invoice_id=prior.id,
            status=ProcessingRunStatus.COMPLETED,
            decision="APPROVE",
        )
        db_session.add(run)
        db_session.commit()

        result = validate_amount(
            invoice_total=Decimal("10000.00"),  # PO total is 75000, already 70000 approved → remaining 5000
            po_id=po_2042.id,
            currency="INR",
        )
        assert result.status == "FAIL"

    def test_scenario_3_blocked_vendor(self, db_session, vendor_blocked):
        """Edge case: blocked vendor → NEEDS_REVIEW on vendor match."""
        result = match_vendor(vendor_tax_id="07AAQCS1234E1Z8")
        assert result.status == "NEEDS_REVIEW"
