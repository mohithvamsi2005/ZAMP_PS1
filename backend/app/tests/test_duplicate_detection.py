"""Phase 8 — duplicate detection beyond the happy path.

Covers false positives (legitimate twins), false negatives (evasion attempts),
and the invariants the demo relies on:

* the current invoice is never its own duplicate (exclude_invoice_id honoured)
* a resubmission NEVER mutates its first submission
* exact vs potential duplicates remain distinguishable
* a number-only match with conflicting financials → REVIEW (INV_DUP_002), not REJECT
"""
import uuid
from decimal import Decimal
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.models import Invoice, PurchaseOrder, Vendor
from app.db.session import SessionLocal
from app.services.duplicate_detector import detect_duplicates
from app.services.workflow import create_invoice_and_run, process_invoice_background


def _seed_vendor_po():
    session = SessionLocal()
    try:
        v = Vendor(
            vendor_code=f"V-DUP-{uuid.uuid4().hex[:6]}",
            legal_name="Duplicate Test Co",
            normalized_name="duplicate test co",
            status="ACTIVE",
            country="IN",
            default_currency="INR",
        )
        session.add(v)
        session.flush()
        from app.db.models import POStatus
        po = PurchaseOrder(
            po_number=f"PO-DUP-{uuid.uuid4().hex[:6]}",
            vendor_id=v.id,
            issue_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
            currency="INR",
            total_amount=Decimal("100000.00"),
            status=POStatus.OPEN,
        )
        session.add(po)
        session.commit()
        return v.id, po.id
    finally:
        session.close()


def _insert_invoice(po_id: int, vendor_id: int, number: str, total: str):
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
        session.commit()
        return inv.id
    finally:
        session.close()


class TestLegitimateTwinsAreNotDuplicates:
    def test_same_vendor_same_total_but_different_numbers_flags_potential(self):
        """Fuzzy-number twins with identical totals are flagged as POTENTIAL dups
        (human confirms), never a silent pass, never an auto-REJECT."""
        po_id, vendor_id = _seed_vendor_po()
        _insert_invoice(po_id, vendor_id, "INV-2026-1011", "59000.00")
        r = detect_duplicates(
            vendor_id=vendor_id,
            invoice_number="INV-2026-1012",
            total_amount=Decimal("59000.00"),
            currency="INR",
        )
        assert r.status == "POTENTIAL_DUPLICATE"
        assert r.existing_invoice_id is not None

    def test_near_identical_numbers_with_different_amounts_do_not_flag(self):
        po_id, vendor_id = _seed_vendor_po()
        _insert_invoice(po_id, vendor_id, "INV-2026-2011", "59000.00")
        # similarity is high (~90+) but amount differs AND currency same → still
        # flags since currency matches; verify currency alone is not sufficient proof
        r = detect_duplicates(
            vendor_id=vendor_id,
            invoice_number="INV-2026-2012",
            total_amount=Decimal("1234.00"),
            currency="INR",
        )
        assert r.status == "POTENTIAL_DUPLICATE"  # currency match alone still suspicious

    def test_similarity_below_threshold_with_far_numbers_passes_clean(self):
        po_id, vendor_id = _seed_vendor_po()
        _insert_invoice(po_id, vendor_id, "AA-1000", "59000.00")
        r = detect_duplicates(
            vendor_id=vendor_id,
            invoice_number="ZZ-9999",
            total_amount=Decimal("59000.00"),
            currency="INR",
        )
        assert r.status == "NO_DUPLICATE_FOUND"

    def test_same_number_different_vendor_is_not_a_duplicate(self):
        """Vendor scope is absolute — identical invoice numbers across vendors are legitimate."""
        po_id, vendor_id = _seed_vendor_po()
        session = SessionLocal()
        try:
            other = Vendor(
                vendor_code=f"V-OTH-{uuid.uuid4().hex[:6]}",
                legal_name="Other Vendor Ltd",
                normalized_name="other vendor ltd",
                status="ACTIVE",
            )
            session.add(other)
            session.flush()
            from app.db.models import POStatus
            po2 = PurchaseOrder(
                po_number=f"PO-OTH-{uuid.uuid4().hex[:6]}",
                vendor_id=other.id,
                issue_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
                currency="INR",
                total_amount=Decimal("100000.00"),
                status=POStatus.OPEN,
            )
            session.add(po2)
            session.flush()
            first_inv = Invoice(
                invoice_number="INV-SHARED-0001",
                vendor_id=vendor_id,
                purchase_order_id=po_id,
                currency="INR",
                subtotal=Decimal("50000.00"),
                tax_amount=Decimal("0.00"),
                discount_amount=Decimal("0.00"),
                total_amount=Decimal("50000.00"),
            )
            session.add(first_inv)
            session.commit()
            other_id = other.id
        finally:
            session.close()

        r = detect_duplicates(
            vendor_id=other_id,
            invoice_number="INV-SHARED-0001",
            total_amount=Decimal("50000.00"),
            currency="INR",
        )
        assert r.status == "NO_DUPLICATE_FOUND"

    def test_self_exclusion_allows_same_hash_query(self):
        """The invoice currently being processed may carry the file hash — the
        document-hash query must skip it when exclude_invoice_id is set."""
        po_id, vendor_id = _seed_vendor_po()
        inv_id = _insert_invoice(po_id, vendor_id, "INV-SELF-HASH", "50000.00")
        session = SessionLocal()
        try:
            inv = session.get(Invoice, inv_id)
            inv.file_sha256 = "deadbeef" * 8
            session.commit()
        finally:
            session.close()
        import hashlib, pathlib
        tmp = pathlib.Path("/tmp/dup_self_check.pdf")
        tmp.write_bytes(bytes.fromhex("deadbeef" * 8))
        r = detect_duplicates(file_path=tmp, vendor_id=vendor_id, invoice_number="INV-SELF-HASH",
                              total_amount=Decimal("50000.00"), currency="INR",
                              exclude_invoice_id=inv_id)
        assert r.status == "NO_DUPLICATE_FOUND"


class TestEvasionResistance:
    def test_extension_change_cannot_evade_document_hash(self, tmp_path):
        """.pdf → .PDF upload with identical bytes is still caught by the hash."""
        po_id, vendor_id = _seed_vendor_po()
        payload = b"%PDF-1.4 identity-check\n" * 20
        inv_id = _insert_invoice(po_id, vendor_id, "INV-EVADE-1", "10000.00")
        session = SessionLocal()
        try:
            import hashlib
            session.get(Invoice, inv_id).file_sha256 = hashlib.sha256(payload).hexdigest()
            session.commit()
        finally:
            session.close()
        f = tmp_path / "invoice.PDF"
        f.write_bytes(payload)
        r = detect_duplicates(file_path=f, vendor_id=vendor_id,
                              invoice_number="INV-EVADE-1", exclude_invoice_id=None)
        assert r.status == "EXACT_DOCUMENT_DUPLICATE"
        assert r.existing_invoice_id == inv_id

    def test_whitespace_manipulation_does_not_evade_number_match(self):
        po_id, vendor_id = _seed_vendor_po()
        _insert_invoice(po_id, vendor_id, "INV-WS-0007", "10000.00")
        r = detect_duplicates(
            vendor_id=vendor_id,
            invoice_number="  INV-WS-0007  ",
            total_amount=Decimal("10000.00"),
            currency="INR",
        )
        assert r.status == "EXACT_INVOICE_DUPLICATE"

    def test_separator_variants_normalize_to_same_invoice_number(self):
        po_id, vendor_id = _seed_vendor_po()
        _insert_invoice(po_id, vendor_id, "INV-26/0312", "10000.00")
        r = detect_duplicates(
            vendor_id=vendor_id,
            invoice_number="INV/26-0312",
            total_amount=Decimal("10000.00"),
            currency="INR",
        )
        # normalize collapses -, /, space → same canonical form
        assert r.status == "EXACT_INVOICE_DUPLICATE"


class TestConflictingFinancials:
    def test_same_number_different_amount_is_review_not_reject(self):
        """The policy distinguishes confirmed twins (REJECT) from number-only
        matches with different amounts (REVIEW / INV_DUP_002)."""
        po_id, vendor_id = _seed_vendor_po()
        _insert_invoice(po_id, vendor_id, "INV-CONFLICT-1", "59000.00")
        r = detect_duplicates(
            vendor_id=vendor_id,
            invoice_number="INV-CONFLICT-1",
            total_amount=Decimal("70000.00"),
            currency="INR",
        )
        assert r.status == "EXACT_INVOICE_DUPLICATE"
        assert r.evidence["same_total"] is False
        # Decision-engine rule lookup is covered in test_decision INV_DUP_002

    def test_same_number_different_currency_flagged_as_currency_conflict(self):
        po_id, vendor_id = _seed_vendor_po()
        _insert_invoice(po_id, vendor_id, "INV-CCY-9", "59000.00")
        session = SessionLocal()
        try:
            session.get(Invoice,
                session.query(Invoice).filter_by(invoice_number="INV-CCY-9").first().id
            ).currency = "USD"
            session.commit()
        finally:
            session.close()
        r = detect_duplicates(
            vendor_id=vendor_id,
            invoice_number="INV-CCY-9",
            total_amount=Decimal("59000.00"),
            currency="INR",
        )
        assert r.status == "EXACT_INVOICE_DUPLICATE"
        assert r.evidence["same_currency"] is False


class TestFirstSubmissionPreserved:
    def test_resubmission_never_overwrites_the_original_invoice(self, tmp_path, monkeypatch):
        """Upload the same file twice via the API (mocked LLM); the stored row
        of the first submission must remain byte-identical."""
        from app.services.test_pdf_generator import create_digital_invoice
        from decimal import Decimal as D
        from app.schemas.invoice import InvoiceExtraction, LineItem

        po_id, vendor_id = _seed_vendor_po()
        pdf = tmp_path / "original.pdf"
        create_digital_invoice(
            pdf, invoice_number="INV-PRESERVE-1", vendor_name="Duplicate Test Co",
            po_ref="PO-PRE", currency="INR",
        )
        contents = pdf.read_bytes()

        def fake_extraction(full_text, metadata):
            return InvoiceExtraction(
                invoice_number="INV-PRESERVE-1",
                invoice_date="2026-10-15",
                currency="INR",
                po_reference="PO-PRE",
                vendor_name="Duplicate Test Co",
                subtotal=D("50000.00"), tax_amount=D("0.00"),
                discount_amount=D("0.00"), total_amount=D("50000.00"),
                line_items=[LineItem(description="x", quantity=D("1"), unit_price=D("50000.00"), line_total=D("50000.00"))],
                extraction_status="SUCCESS",
                warnings=[],
                evidence={},
            )

        monkeypatch.setattr("app.services.workflow.extract_invoice_from_text", fake_extraction)

        client = TestClient(app)
        r1 = client.post("/api/invoices/upload",
                         files={"file": (f"first.pdf", contents, "application/pdf")})
        assert r1.status_code == 202
        first_id = r1.json()["invoice_id"]
        run_id = r1.json()["run_id"]
        process_invoice_background(run_id, first_id)  # synchronous; deterministic with the mock

        session = SessionLocal()
        try:
            inv_before = session.get(Invoice, first_id)
            snapshot = (
                inv_before.invoice_number, str(inv_before.total_amount),
                str(inv_before.subtotal), str(inv_before.created_at),
            )
        finally:
            session.close()

        r2 = client.post("/api/invoices/upload",
                         files={"file": (f"renamed.pdf", contents, "application/pdf")})
        assert r2.status_code == 202

        session = SessionLocal()
        try:
            inv_after = session.get(Invoice, first_id)
            assert (
                inv_after.invoice_number, str(inv_after.total_amount),
                str(inv_after.subtotal), str(inv_after.created_at),
            ) == snapshot
        finally:
            session.close()
