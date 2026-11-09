"""Phase 6 integration tests — full backend workflow.

Covers the complete pipeline as it would run in production:

    POST /api/invoices/upload (PDF) → background processing (document → OCR →
    LLM extraction → matching → validation → deterministic decision →
    persistence) → GET /api/runs/* read APIs.

Isolation rules enforced by conftest.py:
  * Every test runs against a disposable SQLite database (never data/app.db),
    dropped and recreated around each test.
  * Only the LLM is mocked (app.services.workflow.extract_invoice_from_text).
    PDF/OCR processing, matching, duplicate detection, amount/line-item/tax
    validation and the deterministic decision engine all run for real against
    the isolated database.

Scenarios (PS-1 plan §6 + §8):
  1. digital PDF → APPROVE            6. overbilling → REVIEW
  2. scanned PDF via OCR → APPROVE    7. ambiguous vendor → REVIEW
  3. approved PO history → APPROVE    8. LLM failure → run FAILED (technical)
  4. duplicate document → REJECT      9. invalid PDF → 400, nothing stored
  4b. duplicate invoice no. → REJECT 10. event history retrieval
  5. blocked vendor → REJECT         11. result retrieval (+409 while pending)
  12. split PO — second upload sees the updated balance
  13. persistence survives a process restart
  + API surface: 202, filters, 404s, 409s, retry of a FAILED run.
"""
import os
import sqlite3
import time
import uuid
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.models import (
    Invoice, POStatus, ProcessingRun, PurchaseOrder, PurchaseOrderLine,
    Vendor, VendorStatus,
)
from app.db.session import SessionLocal
from app.schemas.invoice import InvoiceExtraction, LineItem
from app.services.run_store import get_run
from app.services.test_pdf_generator import create_digital_invoice, generate_scanned_pdf
from app.services.workflow import create_invoice_and_run


# ── Fixture data constants ───────────────────────────────────────────────────

ACME_NAME = "Acme Industrial Supplies Pvt Ltd"
ACME_TAX_ID = "27AACCA1234F1Z6"
PO_LINE = ("Steel sheets, grade 304", "SS-304-6", "100", "sheets", "500.00", "50000.00")
BLOCKED_VENDOR_NAME = "Sharma Traders Worldwide"
BLOCKED_VENDOR_TAX = "07AAQCS0000E1Z1"

VALID_EVENT_STATUSES = {"PENDING", "RUNNING", "COMPLETED", "WARNING", "FAILED", "SKIPPED"}


@pytest.fixture()
def client():
    return TestClient(app)


# ── Seeding helpers (write directly to the isolated DB) ─────────────────────

def _add_vendor(name: str, tax_id=None, status=VendorStatus.ACTIVE, code=None) -> int:
    session = SessionLocal()
    try:
        v = Vendor(
            vendor_code=code or f"V-WF-{uuid.uuid4().hex[:8]}",
            legal_name=name,
            normalized_name=name.lower(),
            tax_id=tax_id,
            country="IN",
            default_currency="INR",
            status=status,
        )
        session.add(v)
        session.commit()
        return v.id
    finally:
        session.close()


def _add_po(vendor_id: int, po_number: str, total: str, line=PO_LINE,
            status=POStatus.OPEN, currency="INR") -> int:
    session = SessionLocal()
    try:
        po = PurchaseOrder(
            po_number=po_number,
            vendor_id=vendor_id,
            issue_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
            currency=currency,
            total_amount=Decimal(total),
            status=status,
        )
        session.add(po)
        session.flush()
        desc, sku, qty, unit, price, line_total = line
        session.add(PurchaseOrderLine(
            purchase_order_id=po.id, description=desc, sku=sku,
            quantity=Decimal(qty), unit=unit,
            unit_price=Decimal(price), line_total=Decimal(line_total),
        ))
        session.commit()
        return po.id
    finally:
        session.close()


def _seed_approved_history(po_id: int, vendor_id: int, invoice_number: str, total: str) -> int:
    """Insert a completed APPROVE run for a past invoice (committed amount basis)."""
    session = SessionLocal()
    try:
        inv = Invoice(
            invoice_number=invoice_number,
            vendor_id=vendor_id,
            purchase_order_id=po_id,
            currency="INR",
            subtotal=Decimal(total),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal(total),
            invoice_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        session.add(inv)
        session.flush()
        now = datetime.now(timezone.utc)
        session.add(ProcessingRun(
            id=str(uuid.uuid4()), invoice_id=inv.id,
            status="COMPLETED", decision="APPROVE",
            started_at=now, completed_at=now,
        ))
        session.commit()
        return inv.id
    finally:
        session.close()


def seed_env(*, plain_vendor=True, ambig_pair=False, blocked=False) -> dict:
    """Seed a controlled vendor/PO landscape for one test.

    plain_vendor  — Acme (ACTIVE) + PO-WF-1001 (single PO line, total 50000)
    ambig_pair    — two near-identical Acme branch vendors (East/West) + PO-WF-1005
                    (no plain Acme so the ambiguous fuzzy match can fire)
    blocked       — BLOCKED vendor + PO-WF-1004
    """
    out = {}
    if plain_vendor:
        out["vendor_id"] = _add_vendor(ACME_NAME, tax_id=ACME_TAX_ID)
        out["po_id"] = _add_po(out["vendor_id"], "PO-WF-1001", "50000.00")
    if ambig_pair:
        east = _add_vendor("Acme Industrial Supplies East")
        west = _add_vendor("Acme Industrial Supplies West")
        out["east_id"], out["west_id"] = east, west
        out["ambig_po_id"] = _add_po(east, "PO-WF-1005", "50000.00")
    if blocked:
        out["blocked_id"] = _add_vendor(
            BLOCKED_VENDOR_NAME, tax_id=BLOCKED_VENDOR_TAX, status=VendorStatus.BLOCKED,
        )
        out["blocked_po_id"] = _add_po(out["blocked_id"], "PO-WF-1004", "30000.00",
                                       line=("LED panel light 30W", "LED-PNL-30",
                                             "50", "pcs", "600.00", "30000.00"))
    return out


# ── PDF + LLM-mock helpers ───────────────────────────────────────────────────

def _digital_pdf_bytes(tmp_path: Path, **overrides) -> bytes:
    """Render a digital (PDF_TEXT) invoice into tmp_path — never into data/."""
    params = dict(
        invoice_number="INV-WF-0001",
        vendor_name=ACME_NAME,
        po_ref="PO-WF-1001",
        date="2026-10-15",
        due_date="2026-11-14",
        currency="INR",
        subtotal=Decimal("50000.00"),
        tax_amount=Decimal("0.00"),
        discount=Decimal("0.00"),
        total=Decimal("50000.00"),
        line_items=[{
            "description": PO_LINE[0], "quantity": Decimal(PO_LINE[2]),
            "unit": PO_LINE[3], "unit_price": Decimal(PO_LINE[4]),
            "line_total": Decimal(PO_LINE[5]),
        }],
    )
    params.update(overrides)
    path = tmp_path / f"pdf_{uuid.uuid4().hex}.pdf"
    create_digital_invoice(path, **params)
    return path.read_bytes()


def _scanned_pdf_bytes(tmp_path: Path) -> bytes:
    """No text layer at all — forces the OCR fallback (same technique the
    Phase 3 scanned tests use)."""
    path = tmp_path / f"scan_{uuid.uuid4().hex}.pdf"
    generate_scanned_pdf(path)
    return path.read_bytes()


def _extraction(**overrides) -> InvoiceExtraction:
    """A realistic SUCCESS extraction whose fields resolve to the seeded fixture data."""
    params = dict(
        invoice_number="INV-WF-0001",
        invoice_date="2026-10-15",
        due_date="2026-11-14",
        currency="INR",
        po_reference="PO-WF-1001",
        vendor_name=ACME_NAME,
        vendor_tax_id=ACME_TAX_ID,
        subtotal=Decimal("50000.00"),
        tax_amount=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        total_amount=Decimal("50000.00"),
        line_items=[LineItem(
            description=PO_LINE[0], sku=PO_LINE[1], quantity=Decimal(PO_LINE[2]),
            unit=PO_LINE[3], unit_price=Decimal(PO_LINE[4]), line_total=Decimal(PO_LINE[5]),
        )],
        source_pages=[1],
        evidence={
            "invoice_number": {"text": "Invoice: INV-WF-0001", "page": 1, "confidence": 0.98},
            "vendor_name": {"text": ACME_NAME, "page": 1, "confidence": 0.96},
            "total_amount": {"text": "Total: 50000.00", "page": 1, "confidence": 0.97},
        },
        extraction_status="SUCCESS",
        warnings=[],
    )
    params.update(overrides)
    return InvoiceExtraction(**params)


def _mock_llm(monkeypatch, behaviour):
    """
    Mock ONLY the LLM extraction used by the workflow worker.

    behaviour:
      * InvoiceExtraction          → returned for every call
      * Exception instance/class   → raised for every call (technical failure)
      * list of the above          → consumed in order (multi-upload tests)
      * callable(text, metadata)   → invoked directly
    """
    if callable(behaviour) and not isinstance(behaviour, BaseException):
        fake = behaviour
    elif isinstance(behaviour, BaseException) or (
        isinstance(behaviour, type) and issubclass(behaviour, BaseException)
    ):
        def fake(full_text, metadata):
            raise behaviour
    elif isinstance(behaviour, InvoiceExtraction):
        def fake(full_text, metadata):
            return behaviour
    else:  # sequence
        remaining = list(behaviour)

        def fake(full_text, metadata):
            item = remaining.pop(0)
            if isinstance(item, BaseException):
                raise item
            if isinstance(item, type) and issubclass(item, BaseException):
                raise item("mock failure")
            return item

    monkeypatch.setattr("app.services.workflow.extract_invoice_from_text", fake)


def _run_existing_pdf(client, monkeypatch, mock, pdf_bytes, filename="invoice.pdf"):
    """Upload the exact bytes we pass in (unlike _digital_pdf_bytes which
    generates fresh content) — needed for same-bytes resubmission tests."""
    _mock_llm(monkeypatch, mock)
    _invoice_id, run_id = _upload(client, pdf_bytes, filename)
    return _wait_terminal(run_id)


# ── Upload / polling helpers ─────────────────────────────────────────────────

def _upload(client: TestClient, data: bytes, filename="invoice.pdf"):
    resp = client.post("/api/invoices/upload",
                       files={"file": (filename, data, "application/pdf")})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "PENDING"
    assert body["invoice_id"] and body["run_id"]
    return body["invoice_id"], body["run_id"]


def _wait_terminal(run_id: str, timeout: float = 60.0) -> dict:
    """Poll the read API until the run reaches COMPLETED or FAILED.

    Uses the public run store (the API's own persistence path), not internal
    handles, so the assertions exercise exactly what production reads see.
    """
    deadline = time.monotonic() + timeout
    last_status = None
    while time.monotonic() < deadline:
        data = get_run(run_id)
        assert data is not None, f"run {run_id} vanished"
        last_status = data["status"]
        if last_status in ("COMPLETED", "FAILED"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"Run {run_id} never finished; last status={last_status}")


def _upload_and_process(client, monkeypatch, tmp_path, mock, **pdf_overrides):
    pdf_bytes = _digital_pdf_bytes(tmp_path, **pdf_overrides)
    _mock_llm(monkeypatch, mock)
    _invoice_id, run_id = _upload(client, pdf_bytes)
    return _wait_terminal(run_id)


def _stage_events(data: dict, stage: str):
    return [e for e in data["events"] if e["stage"] == stage]


def _rule_ids(decision_result: dict):
    return {r["rule_id"] for r in decision_result["rules_evaluated"]}


def _invoice_count() -> int:
    session = SessionLocal()
    try:
        return session.query(Invoice).count()
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════════════════════
# Scenario 1–3, 12: APPROVE paths and PO balance accounting
# ══════════════════════════════════════════════════════════════════════════════

class TestApprovalPaths:
    def test_digital_invoice_full_approve(self, monkeypatch, client, tmp_path):
        """Scenario 1 — digital PDF through every stage, all checks pass."""
        env = seed_env()
        data = _upload_and_process(
            client, monkeypatch, tmp_path, _extraction(),
            invoice_number="INV-WF-0001",
        )

        assert data["status"] == "COMPLETED"
        assert data["decision"] == "APPROVE"
        assert data["started_at"] is not None
        assert data["completed_at"] is not None
        assert data["llm_provider"], "run must record which LLM produced the decision"
        assert data["error_message"] is None

        dr = data["decision_result"]
        assert dr["decision"] == "APPROVE"
        assert dr["approval_eligible"] is True
        assert dr["hard_failures"] == []
        assert dr["review_reasons"] == []
        assert "APPROVE_001" in _rule_ids(dr)

        # Every cross-check ran against the real isolated DB
        assert data["vendor_match"]["status"] == "MATCHED"
        assert data["po_match"]["status"] == "MATCHED"
        # Self-exclusion: the current invoice row was already persisted with
        # its hash/vendor/number before this check ran — it must not be found
        # as its own duplicate.
        assert data["duplicate_check"]["status"] == "NO_DUPLICATE_FOUND"
        assert data["duplicate_check"]["evidence"]["excluded_invoice_id"] == data["invoice_id"]

        assert data["amount_validation"]["status"] == "PASS"
        assert data["amount_validation"]["metadata"]["provisional"] is False
        assert data["amount_validation"]["remaining_po_balance"] == "0.00"
        assert data["line_item_validation"]["status"] == "PASS"
        assert data["tax_validation"]["status"] == "PASS"

        # Persisted invoice + extraction
        inv = data["invoice"]
        assert inv["invoice_number"] == "INV-WF-0001"
        assert inv["vendor_id"] == env["vendor_id"]
        assert inv["purchase_order_id"] == env["po_id"]
        assert inv["total_amount"] == "50000.00"
        assert inv["currency"] == "INR"
        assert len(inv["line_items"]) == 1
        assert inv["line_items"][0]["description"] == PO_LINE[0]
        assert data["extraction"]["invoice_number"] == "INV-WF-0001"
        assert data["extraction"]["total_amount"] == "50000.00"

        # The uploaded bytes are kept under the isolated upload dir under a
        # generated server-side name (never the user-supplied filename)
        stored = list(Path(os.environ["UPLOAD_DIR"]).glob("*.pdf"))
        assert stored, "uploaded PDF should exist under UPLOAD_DIR"
        assert all(p.stat().st_size > 0 for p in stored)

    def test_scanned_invoice_ocr_approve(self, monkeypatch, client, tmp_path):
        """Scenario 2 — page has no text layer; OCR fallback produces the text."""
        env = seed_env()
        pdf_bytes = _scanned_pdf_bytes(tmp_path)
        _mock_llm(monkeypatch, _extraction(invoice_number="INV-WF-SCAN-1"))
        _invoice_id, run_id = _upload(client, pdf_bytes, "scan.pdf")
        data = _wait_terminal(run_id)

        assert data["status"] == "COMPLETED"
        assert data["decision"] == "APPROVE"

        # OCR actually ran (not skipped) and completed
        ocr_events = _stage_events(data, "OCR_PROCESSING")
        assert ocr_events, "OCR stage must have produced an event"
        assert any(e["status"] == "RUNNING" for e in ocr_events)
        completed = [e for e in ocr_events if e["status"] == "COMPLETED"]
        assert completed, "OCR must complete successfully for the scanned invoice"
        assert completed[-1]["details"]["ocr_pages"] == [1]

        # Document metadata reflects the OCR recovery — and the obsolete
        # "no extractable text" warning is gone (it recovered), otherwise every
        # scanned invoice would be forced into REVIEW by EXTRACTION_001.
        pages = data["document_meta"]["pages_processed"]
        assert pages[0]["method"] == "OCR"
        assert data["document_meta"]["warnings"] == []

        # LLM, matching and validations still run on top of the OCR text
        assert data["extraction"]["invoice_number"] == "INV-WF-SCAN-1"
        assert data["vendor_match"]["status"] == "MATCHED"
        assert data["po_match"]["status"] == "MATCHED"
        assert data["duplicate_check"]["status"] == "NO_DUPLICATE_FOUND"
        assert data["amount_validation"]["status"] == "PASS"
        assert data["line_item_validation"]["status"] == "PASS"
        assert data["tax_validation"]["status"] == "PASS"
        assert data["decision_result"]["approval_eligible"] is True

    def test_approved_po_balance_partial_billing_approve(self, monkeypatch, client, tmp_path):
        """Scenario 3 — APPROVE counted against real approved history (not provisional)."""
        env = seed_env()
        vendor_id = env["vendor_id"]
        second_po = _add_po(vendor_id, "PO-WF-1002", "90000.00")
        _seed_approved_history(second_po, vendor_id, "INV-WF-HIST-1", "40000.00")

        data = _upload_and_process(
            client, monkeypatch, tmp_path,
            _extraction(invoice_number="INV-WF-0002", po_reference="PO-WF-1002"),
            invoice_number="INV-WF-0002",
        )

        assert data["status"] == "COMPLETED"
        assert data["decision"] == "APPROVE"
        amt = data["amount_validation"]
        assert amt["status"] == "PASS"
        assert amt["metadata"]["provisional"] is False, \
            "approved history must exist → basis is committed, not provisional"
        assert amt["previously_approved_invoiced"] == "40000.00"
        assert amt["po_total"] == "90000.00"
        assert amt["remaining_po_balance"] == "0.00"
        # The invoice is attributed to the right PO/vendor
        assert data["invoice"]["purchase_order_id"] == second_po
        assert data["invoice"]["vendor_id"] == vendor_id
        assert data["decision_result"]["approval_eligible"] is True

    def test_split_po_second_upload_sees_updated_balance(self, monkeypatch, client, tmp_path):
        """Scenario 12 — after one APPROVE consumes the balance, the next
        upload against the same PO sees the reduced balance → amount FAIL →
        REVIEW (never a silent APPROVE)."""
        env = seed_env()
        # First invoice covers the only PO line exactly and is approved.
        first = _upload_and_process(
            client, monkeypatch, tmp_path,
            _extraction(invoice_number="INV-WF-SPLIT-1"),
            invoice_number="INV-WF-SPLIT-1",
        )
        assert first["decision"] == "APPROVE"
        assert first["amount_validation"]["remaining_po_balance"] == "0.00"

        # Second invoice: different bytes, different number, same total →
        # now exceeds the remaining balance by 50000 → FAIL → REVIEW.
        second = _upload_and_process(
            client, monkeypatch, tmp_path,
            _extraction(invoice_number="INV-SP-10001"),
            invoice_number="INV-SP-10001", date="2026-10-16",
        )

        assert second["status"] == "COMPLETED"
        assert second["decision"] == "REVIEW"
        amt = second["amount_validation"]
        assert amt["status"] == "FAIL"
        assert amt["previously_approved_invoiced"] == "50000.00", \
            "the first (approved) invoice must count as a committed amount"
        assert amt["remaining_po_balance"] == "0.00"
        assert amt["metadata"]["provisional"] is False
        dr = second["decision_result"]
        assert "AMOUNT_001" in _rule_ids(dr)
        assert any("exceeds" in r for r in dr["review_reasons"])
        # Non-defective checks stay PASS — the review is purely about balance
        assert second["line_item_validation"]["status"] == "PASS"
        assert second["tax_validation"]["status"] == "PASS"
        assert second["duplicate_check"]["status"] == "NO_DUPLICATE_FOUND"


# ══════════════════════════════════════════════════════════════════════════════
# Scenarios 4–5: hard REJECT business decisions
# ══════════════════════════════════════════════════════════════════════════════

class TestRejectPaths:
    def test_exact_document_duplicate_rejected(self, monkeypatch, client, tmp_path):
        """Scenario 4 — identical bytes re-uploaded → REJECT (DOC_DUP_001).

        The FIRST upload of those bytes must NOT have flagged itself as its own
        duplicate (self-exclusion regression check).
        """
        env = seed_env()
        pdf_bytes = _digital_pdf_bytes(tmp_path, invoice_number="INV-WF-DUP-1")

        first = _run_existing_pdf(
            client, monkeypatch, _extraction(invoice_number="INV-WF-DUP-1"), pdf_bytes,
        )
        assert first["status"] == "COMPLETED"
        assert first["decision"] == "APPROVE"
        assert first["duplicate_check"]["status"] == "NO_DUPLICATE_FOUND"

        # Re-upload the exact same file. The extraction "sees" a different
        # invoice number (LLM variability), but the document hash is identical.
        second = _run_existing_pdf(
            client, monkeypatch, _extraction(invoice_number="INV-WF-DUP-1B"), pdf_bytes,
        )

        assert second["status"] == "COMPLETED"
        assert second["decision"] == "REJECT"
        dup = second["duplicate_check"]
        assert dup["status"] == "EXACT_DOCUMENT_DUPLICATE"
        # It matched the FIRST submission — never itself
        assert dup["existing_invoice_id"] == first["invoice_id"]
        assert dup["evidence"]["matched_invoice_number"] == "INV-WF-DUP-1"
        dr = second["decision_result"]
        assert "DOC_DUP_001" in _rule_ids(dr)
        assert dr["hard_failures"]
        assert dr["approval_eligible"] is False

    def test_exact_invoice_number_duplicate_rejected(self, monkeypatch, client, tmp_path):
        """Scenario 4b — different file, same vendor + invoice number → REJECT."""
        env = seed_env()
        _upload_and_process(
            client, monkeypatch, tmp_path,
            _extraction(invoice_number="INV-WF-DUP-9"),
            invoice_number="INV-WF-DUP-9",
        )
        second = _upload_and_process(
            client, monkeypatch, tmp_path,
            _extraction(invoice_number="INV-WF-DUP-9"),
            invoice_number="INV-WF-DUP-9", date="2026-10-16",
        )

        assert second["status"] == "COMPLETED"
        assert second["decision"] == "REJECT"
        dup = second["duplicate_check"]
        assert dup["status"] == "EXACT_INVOICE_DUPLICATE"
        assert dup["evidence"]["same_total"] is True
        assert dup["evidence"]["same_currency"] is True
        dr = second["decision_result"]
        assert "INV_DUP_001" in _rule_ids(dr)

    def test_blocked_vendor_rejected(self, monkeypatch, client, tmp_path):
        """Scenario 5 — invoice from a BLOCKED vendor → REJECT (VENDOR_BLOCK_001)."""
        env = seed_env(blocked=True)
        data = _upload_and_process(
            client, monkeypatch, tmp_path,
            _extraction(
                vendor_name=BLOCKED_VENDOR_NAME,
                vendor_tax_id=BLOCKED_VENDOR_TAX,
                po_reference="PO-WF-1004",
                invoice_number="INV-WF-BLK-1",
                subtotal=Decimal("30000.00"),
                total_amount=Decimal("30000.00"),
                line_items=[LineItem(
                    description="LED panel light 30W", sku="LED-PNL-30",
                    quantity=Decimal("50"), unit="pcs",
                    unit_price=Decimal("600.00"), line_total=Decimal("30000.00"),
                )],
            ),
            invoice_number="INV-WF-BLK-1",
        )

        assert data["status"] == "COMPLETED", \
            "REJECT is a business decision on a COMPLETED run, not a failure"
        assert data["decision"] == "REJECT"
        assert data["vendor_match"]["status"] == "NEEDS_REVIEW"
        assert data["vendor_match"]["matched_vendor"]["id"] == env["blocked_id"]
        dr = data["decision_result"]
        assert "VENDOR_BLOCK_001" in _rule_ids(dr)
        assert any("BLOCKED" in f for f in dr["hard_failures"])
        assert dr["approval_eligible"] is False


# ══════════════════════════════════════════════════════════════════════════════
# Scenarios 6–7: REVIEW business decisions
# ══════════════════════════════════════════════════════════════════════════════

class TestReviewPaths:
    def test_overbilling_invoice_goes_to_review(self, monkeypatch, client, tmp_path):
        """Scenario 6 — invoice exceeds the remaining PO balance after an
        approved invoice consumed it → REVIEW (AMOUNT_001), never silent."""
        env = seed_env()
        first = _upload_and_process(
            client, monkeypatch, tmp_path,
            _extraction(invoice_number="INV-WF-OVR-1"),
            invoice_number="INV-WF-OVR-1",
        )
        assert first["decision"] == "APPROVE"
        assert first["amount_validation"]["remaining_po_balance"] == "0.00"

        # Same total again, different bytes/number → exceeds the balance by 50000
        second = _upload_and_process(
            client, monkeypatch, tmp_path,
            _extraction(invoice_number="INV-ZR-70002"),
            invoice_number="INV-ZR-70002", date="2026-10-16",
        )

        assert second["status"] == "COMPLETED"
        assert second["decision"] == "REVIEW"
        amt = second["amount_validation"]
        assert amt["status"] == "FAIL"
        assert amt["previously_approved_invoiced"] == "50000.00"
        assert amt["remaining_po_balance"] == "0.00"
        assert amt["difference"] == "50000.00"
        assert "AMOUNT_001" in _rule_ids(second["decision_result"])
        # Non-amount checks stay PASS — the review is purely the balance
        assert second["line_item_validation"]["status"] == "PASS"
        assert second["tax_validation"]["status"] == "PASS"

    def test_ambiguous_vendor_review(self, monkeypatch, client, tmp_path):
        """Scenario 7 — vendor name that plausibly matches two vendors → REVIEW."""
        env = seed_env(plain_vendor=False, ambig_pair=True)
        data = _upload_and_process(
            client, monkeypatch, tmp_path,
            _extraction(
                vendor_name="Acme Industrial Supplies",   # matches BOTH branch vendors
                vendor_tax_id=None,
                po_reference="PO-WF-1005",
                invoice_number="INV-WF-AMB-1",
            ),
            invoice_number="INV-WF-AMB-1",
        )

        assert data["status"] == "COMPLETED"
        assert data["decision"] == "REVIEW"
        vm = data["vendor_match"]
        assert vm["status"] == "AMBIGUOUS"
        assert vm["matched_vendor"] is None
        assert len(vm["candidates"]) >= 2, \
            f"expected several fuzzy candidates, got {vm['candidates']}"
        # The invoice must not be attributed to either candidate
        assert data["invoice"]["vendor_id"] is None
        dr = data["decision_result"]
        assert "VENDOR_002" in _rule_ids(dr)
        assert any("human" in r.lower() for r in dr["review_reasons"])
        assert dr["approval_eligible"] is False


# ══════════════════════════════════════════════════════════════════════════════
# Partial line-item data: deterministic derivation, never fabrication
# ══════════════════════════════════════════════════════════════════════════════

class TestPartialLineData:
    def test_line_total_derived_from_qty_and_price(self, monkeypatch, client, tmp_path):
        """LLM omits line_total → derived as qty × price; invoice persists."""
        seed_env()
        data = _upload_and_process(
            client, monkeypatch, tmp_path,
            _extraction(
                invoice_number="INV-WF-DERIVE-1",
                line_items=[LineItem(
                    description=PO_LINE[0], sku=PO_LINE[1], quantity=Decimal("100"),
                    unit="sheets", unit_price=Decimal("500.00"), line_total=None,
                )],
            ),
            invoice_number="INV-WF-DERIVE-1",
        )
        assert data["status"] == "COMPLETED"
        lines = data["invoice"]["line_items"]
        assert len(lines) == 1
        assert lines[0]["line_total"] == "50000.00"
        assert data["line_item_validation"]["status"] == "PASS"
        assert data["decision"] == "APPROVE"

    def test_unrecoverable_line_skipped_run_survives(self, monkeypatch, client, tmp_path):
        """LLM gives a line with neither price nor total → the line is omitted
        (never fabricated), a warning is attached and the invoice goes to a
        human (REVIEW), not a TAX crash."""
        seed_env()
        data = _upload_and_process(
            client, monkeypatch, tmp_path,
            _extraction(
                invoice_number="INV-WF-NOLINE-1",
                line_items=[LineItem(
                    description="Mystery item", sku=None, quantity=Decimal("3"),
                    unit="pcs", unit_price=None, line_total=None,
                )],
            ),
            invoice_number="INV-WF-NOLINE-1",
        )
        assert data["status"] == "COMPLETED", \
            "a missing line body must not crash the run to FAILED"
        assert data["invoice"]["line_items"] == []
        assert any("1 line item(s) omitted" in w for w in data["extraction"]["warnings"])
        assert data["line_item_validation"]["status"] == "WARNING"
        assert data["decision"] == "REVIEW"


# ══════════════════════════════════════════════════════════════════════════════
# Scenarios 8–9 + retry: technical failures must never become business decisions
# ══════════════════════════════════════════════════════════════════════════════

class TestTechnicalFailures:
    def test_llm_failure_marks_run_failed(self, monkeypatch, client, tmp_path):
        """Scenario 8 — LLM extraction raises → run FAILED, no decision."""
        seed_env()
        pdf_bytes = _digital_pdf_bytes(tmp_path, invoice_number="INV-WF-FAIL-1")
        _mock_llm(monkeypatch, RuntimeError("simulated LLM provider outage"))
        _invoice_id, run_id = _upload(client, pdf_bytes)
        data = _wait_terminal(run_id)

        assert data["status"] == "FAILED"
        assert data["decision"] is None, "a technical failure must never produce a decision"
        assert data["completed_at"] is None
        assert "LLM extraction failed" in (data["error_message"] or "")

        failed_events = _stage_events(data, "FAILED")
        assert failed_events and failed_events[-1]["status"] == "FAILED"
        assert "simulated LLM provider outage" in (failed_events[-1]["message"] or "")
        # No COMPLETED / PERSISTENCE event — pipeline stopped at the failure
        assert not _stage_events(data, "COMPLETED")
        assert not _stage_events(data, "PERSISTENCE")

        # The result endpoint still answers (200) but without a decision
        resp = client.get(f"/api/runs/{run_id}/result")
        assert resp.status_code == 200
        assert resp.json()["decision"] is None
        assert resp.json()["status"] == "FAILED"

    def test_retry_of_failed_run_completes(self, monkeypatch, client, tmp_path):
        """A FAILED run can be re-queued; history is preserved and the retry
        runs the full pipeline again (retry-safe persistence: no double lines)."""
        seed_env()
        pdf_bytes = _digital_pdf_bytes(tmp_path, invoice_number="INV-WF-RETRY-1")
        _mock_llm(monkeypatch, RuntimeError("first attempt fails"))
        _invoice_id, run_id = _upload(client, pdf_bytes)
        failed = _wait_terminal(run_id)
        assert failed["status"] == "FAILED"
        events_after_failure = len(failed["events"])

        # Re-point the mock at a working extraction and retry via the API
        _mock_llm(monkeypatch, _extraction())
        resp = client.post(f"/api/runs/{run_id}/retry")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "PENDING"

        retried = _wait_terminal(run_id)
        assert retried["status"] == "COMPLETED"
        assert retried["decision"] == "APPROVE"
        # Retry-safe: same invoice, exactly one line item (not two)
        assert len(retried["invoice"]["line_items"]) == 1
        # Previous attempt's failure history is preserved
        assert len(retried["events"]) > events_after_failure
        assert any(
            e["stage"] == "FAILED" and e["status"] == "FAILED"
            for e in retried["events"]
        )

        # Retrying a finished run is not allowed
        resp = client.post(f"/api/runs/{run_id}/retry")
        assert resp.status_code == 409

    def test_retry_unknown_run_404(self, client):
        resp = client.post("/api/runs/does-not-exist/retry")
        assert resp.status_code == 404

    def test_invalid_pdf_rejected_before_persistence(self, client, tmp_path):
        """Scenario 9 — structurally invalid uploads are rejected with 400 and
        leave no invoice/run rows behind."""
        cases = [
            (b"this is absolutely not a pdf", "fake.pdf", "Invalid PDF"),
            (b"", "empty.pdf", "Empty file"),
        ]
        for payload, name, expected_detail in cases:
            resp = client.post("/api/invoices/upload",
                               files={"file": (name, payload, "application/pdf")})
            assert resp.status_code == 400, (name, resp.text)
            assert expected_detail.lower() in resp.json()["detail"].lower(), (name, resp.text)

        resp = client.post(
            "/api/invoices/upload",
            files={"file": ("notes.txt", b"hello world", "text/plain")},
        )
        assert resp.status_code == 400
        assert "Only PDF files are accepted" in resp.json()["detail"]

        assert _invoice_count() == 0


# ══════════════════════════════════════════════════════════════════════════════
# Scenarios 10–13: read APIs, event history, restart durability
# ══════════════════════════════════════════════════════════════════════════════

class TestRunReadAPIs:
    def test_events_endpoint_returns_full_stage_history(self, monkeypatch, client, tmp_path):
        """Scenario 10 — the persisted event trail is complete and ordered."""
        seed_env()
        data = _upload_and_process(
            client, monkeypatch, tmp_path, _extraction(invoice_number="INV-WF-EVNT-1"),
            invoice_number="INV-WF-EVNT-1",
        )
        resp = client.get(f"/api/runs/{data['run_id']}/events")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 13, f"expected the full stage history, got {len(events)}"

        ids = [e["id"] for e in events]
        assert ids == sorted(ids), "events must be chronological"

        stages = [e["stage"] for e in events]
        for expected in ("RECEIVED", "DOCUMENT_PROCESSING", "OCR_PROCESSING",
                         "LLM_EXTRACTION", "VENDOR_MATCHING", "PO_MATCHING",
                         "DUPLICATE_CHECK", "AMOUNT_VALIDATION", "LINE_ITEM_VALIDATION",
                         "TAX_VALIDATION", "DECISION", "PERSISTENCE", "COMPLETED"):
            assert expected in stages, f"missing stage {expected}"

        # Digital invoice → OCR skipped, never a FAILED event
        ocr_events = [e for e in events if e["stage"] == "OCR_PROCESSING"]
        assert all(e["status"] == "SKIPPED" for e in ocr_events)
        assert all(e["status"] in VALID_EVENT_STATUSES for e in events)

        # Events carry structured key facts, never raw document text
        doc_event = next(e for e in events
                         if e["stage"] == "DOCUMENT_PROCESSING" and e["status"] == "COMPLETED")
        assert doc_event["details"]["page_count"] == 1
        assert doc_event["details"]["total_chars_extracted"] > 0
        for e in events:
            blob = (e["message"] or "") + repr(e["details"])
            assert len(blob) < 3000, "event payloads must stay summary-sized"

    def test_result_endpoint_full_payload(self, monkeypatch, client, tmp_path):
        """Scenario 11 — decision + all supporting stage results in one call."""
        seed_env()
        data = _upload_and_process(
            client, monkeypatch, tmp_path, _extraction(invoice_number="INV-WF-RES-1"),
            invoice_number="INV-WF-RES-1",
        )
        resp = client.get(f"/api/runs/{data['run_id']}/result")
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "COMPLETED"
        assert result["decision"] == "APPROVE"
        # every persisted section is present
        for section in ("extraction", "document_meta", "vendor_match", "po_match",
                        "duplicate_check", "amount_validation", "line_item_validation",
                        "tax_validation", "decision_result", "invoice"):
            assert result[section] is not None, f"{section} missing from result"

    def test_result_409_while_pending(self, client, tmp_path):
        """A queued (PENDING) run has no result yet → 409 Conflict."""
        pdf_bytes = _digital_pdf_bytes(tmp_path)
        _invoice_id, run_id = create_invoice_and_run(pdf_bytes, "pending.pdf")  # not processed
        resp = client.get(f"/api/runs/{run_id}/result")
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "PENDING" in detail

        detail_resp = client.get(f"/api/runs/{run_id}")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["status"] == "PENDING"

    def test_unknown_run_404s(self, client):
        assert client.get("/api/runs/nope").status_code == 404
        assert client.get("/api/runs/nope/events").status_code == 404
        assert client.get("/api/runs/nope/result").status_code == 404

    def test_runs_list_filters_and_pagination(self, monkeypatch, client, tmp_path):
        seed_env()
        pdf_bytes = _digital_pdf_bytes(tmp_path, invoice_number="INV-WF-LIST-1")
        approved = _run_existing_pdf(
            client, monkeypatch, _extraction(invoice_number="INV-WF-LIST-1"), pdf_bytes,
        )
        rejected = _run_existing_pdf(  # identical bytes → confirmed duplicate → REJECT
            client, monkeypatch, _extraction(invoice_number="INV-LC-80002"), pdf_bytes,
        )

        resp = client.get("/api/runs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["page_size"] == 20
        statuses = {r["status"] for r in body["runs"]}
        assert statuses == {"COMPLETED"}
        run_ids = {r["run_id"] for r in body["runs"]}
        assert {approved["run_id"], rejected["run_id"]} <= run_ids

        resp = client.get("/api/runs", params={"decision": "APPROVE"})
        rows = resp.json()["runs"]
        assert {r["decision"] for r in rows} == {"APPROVE"}

        resp = client.get("/api/runs", params={"decision": "REJECT"})
        rows = resp.json()["runs"]
        assert {r["decision"] for r in rows} == {"REJECT"}
        assert rejected["run_id"] in {r["run_id"] for r in rows}

        resp = client.get("/api/runs", params={"invoice_id": approved["invoice_id"]})
        rows = resp.json()["runs"]
        assert {r["invoice_id"] for r in rows} == {approved["invoice_id"]}

        resp = client.get("/api/runs", params={"page_size": 1, "page": 1})
        body = resp.json()
        assert body["page_size"] == 1 and len(body["runs"]) == 1 and body["total"] == 2

        resp = client.get("/api/runs", params={"status": "UNICORNS"})
        assert resp.status_code == 422

    def test_invoice_detail_endpoint(self, monkeypatch, client, tmp_path):
        seed_env()
        data = _upload_and_process(
            client, monkeypatch, tmp_path, _extraction(invoice_number="INV-WF-DETAIL-1"),
            invoice_number="INV-WF-DETAIL-1",
        )
        resp = client.get(f"/api/invoices/{data['invoice_id']}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["invoice_number"] == "INV-WF-DETAIL-1"
        assert body["file_sha256"], "upload record must store the document hash"
        assert len(body["line_items"]) == 1
        assert len(body["processing_runs"]) == 1
        assert body["processing_runs"][0]["run_id"] == data["run_id"]
        assert body["processing_runs"][0]["decision"] == "APPROVE"

        resp = client.get("/api/invoices/999999")
        assert resp.status_code == 404


class TestRestartDurability:
    def test_results_survive_process_restart(self, monkeypatch, client, tmp_path, test_db_path):
        """Scenario 13 — everything needed to reconstruct a run lives in the
        database (plus the isolated file), so a server restart loses nothing."""
        seed_env()
        data = _upload_and_process(
            client, monkeypatch, tmp_path, _extraction(invoice_number="INV-WF-RST-1"),
            invoice_number="INV-WF-RST-1",
        )
        run_id = data["run_id"]

        # Simulate the restart: read the run back with a completely fresh
        # application state (new session, then the direct file).
        conn = sqlite3.connect(str(test_db_path))
        try:
            row = conn.execute(
                "SELECT status, decision, error_message FROM processing_runs WHERE id=?",
                (run_id,),
            ).fetchone()
            assert row is not None, "run row must be on disk at the isolated DB path"
            assert row[0] == "COMPLETED"
            assert row[1] == "APPROVE"
            assert row[2] is None

            event_count = conn.execute(
                "SELECT COUNT(*) FROM run_events WHERE processing_run_id=?", (run_id,)
            ).fetchone()[0]
            assert event_count >= 13

            json_columns = conn.execute(
                "SELECT extraction_json, decision_json, amount_validation_json, "
                "tax_validation_json, document_meta_json FROM processing_runs WHERE id=?",
                (run_id,),
            ).fetchone()
            assert all(col is not None for col in json_columns)
        finally:
            conn.close()

        # And the API layer serves the same data after "restart"
        resp = client.get(f"/api/runs/{run_id}/result")
        assert resp.status_code == 200
        assert resp.json()["decision"] == "APPROVE"
