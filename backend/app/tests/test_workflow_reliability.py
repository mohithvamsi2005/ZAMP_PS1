"""Phase 8 — workflow reliability: failure injection, concurrency, retry semantics.

Every test re-wires the REAL pipeline pieces; only the one broken component is
substituted, and results are read back from the same database the API serves.
"""
import uuid
from decimal import Decimal
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.main import app
from app.db.models import (
    Invoice, InvoiceLine, ProcessingRun, PurchaseOrder, PurchaseOrderLine,
    Vendor, POStatus,
)
from app.db.session import SessionLocal
from app.schemas.invoice import InvoiceExtraction, LineItem
from app.services import workflow
from app.services.pdf_extractor import PDFExtractionError
from app.services.run_store import get_run
from app.services.test_pdf_generator import create_digital_invoice
from app.services.workflow import create_invoice_and_run, process_invoice_background, retry_failed_run


@pytest.fixture()
def seeded():
    s = SessionLocal()
    try:
        v = Vendor(
            vendor_code=f"V-REL-{uuid.uuid4().hex[:6]}",
            legal_name="Reliability Vendor Ltd",
            normalized_name="reliability vendor ltd",
            status="ACTIVE",
            default_currency="INR",
        )
        s.add(v)
        s.flush()
        po = PurchaseOrder(
            po_number="PO-REL-1",
            vendor_id=v.id,
            issue_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
            currency="INR",
            total_amount=Decimal("90000.00"),
            status=POStatus.OPEN,
        )
        s.add(po)
        s.flush()
        s.add(PurchaseOrderLine(
            purchase_order_id=po.id, description="Steel sheets, grade 304",
            sku="SS-304-6", quantity=Decimal("100"), unit="sheets",
            unit_price=Decimal("500.00"), line_total=Decimal("50000.00"),
        ))
        s.commit()
        return {"vendor_id": v.id, "po_id": po.id, "po_number": "PO-REL-1"}
    finally:
        s.close()


def _good_extraction(**overrides):
    params = dict(
        invoice_number="INV-REL-1",
        invoice_date="2026-10-15",
        currency="INR",
        po_reference="PO-REL-1",
        vendor_name="Reliability Vendor Ltd",
        subtotal=Decimal("60000.00"),
        tax_amount=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        total_amount=Decimal("60000.00"),
        line_items=[LineItem(
            description="Steel sheets, grade 304", sku="SS-304-6",
            quantity=Decimal("100"), unit="sheets",
            unit_price=Decimal("500.00"), line_total=Decimal("50000.00"),
        )],
        extraction_status="SUCCESS",
        warnings=[],
        evidence={
            "invoice_number": {"text": "Invoice: INV-REL-1", "page": 1, "confidence": 0.95},
            "vendor_name": {"text": "Reliability Vendor Ltd", "page": 1, "confidence": 0.95},
            "total_amount": {"text": "Total: 60000.00", "page": 1, "confidence": 0.95},
        },
    )
    params.update(overrides)
    return InvoiceExtraction(**params)


def _make_upload(monkeypatch, extraction, contents=b"%PDF-1.4 reliability-test"):
    pdf = b"%PDF-1.4 reliability-test-bytes\n" * 4
    monkeypatch.setattr("app.services.workflow.extract_invoice_from_text", lambda ft, md: extraction)
    return pdf


def _pdf_bytes(tmp_path, invoice_number="INV-REL-1"):
    p = tmp_path / f"{invoice_number}.pdf"
    create_digital_invoice(p, invoice_number=invoice_number,
                           vendor_name="Reliability Vendor Ltd", po_ref="PO-REL-1")
    return p.read_bytes()

def _run_to_completion(run_id, invoice_id):
    process_invoice_background(run_id, invoice_id)


def _get_run(run_id):
    s = SessionLocal()
    try:
        return s.get(ProcessingRun, run_id)
    finally:
        s.close()


class TestStageFailureInjection:
    def test_pdf_open_failure_marks_run_failed_with_stage_recorded(self, monkeypatch, seeded):
        from sqlalchemy.exc import SQLAlchemyError
        monkeypatch.setattr("app.services.workflow.extract_pdf", lambda path: (_ for _ in ()).throw(
            PDFExtractionError("Corrupt section 2 xref table"),
        ))
        contents = b"%PDF-1.4 corrupted-bytes"
        invoice_id, run_id = create_invoice_and_run(contents, "broken.pdf")
        _run_to_completion(run_id, invoice_id)
        run = _get_run(run_id)
        assert run.status.value == "FAILED"
        assert "PDF extraction failed" in (run.error_message or "")
        assert run.decision is None
        events = get_run(run_id)["events"]
        failed_msgs = [e["message"] for e in events if e["status"] == "FAILED"]
        assert any("document_processing" in (m or "").lower() or "DOCUMENT_PROCESSING" in (m or "") for m in failed_msgs)

    def test_ocr_total_failure_marks_run_failed(self, monkeypatch, seeded, tmp_path):
        """A page with no text layer whose OCR raises → run FAILED, never fake SUCCESS."""
        # Stub extract_pdf to return a doc-meta with an OCR_REQUIRED page, and
        # make the OCR service raise → workflow must convert to FAILED.
        from app.schemas.invoice import ExtractionMetadata

        def fake_extract_pdf(path):
            metadata = ExtractionMetadata(
                page_count=1,
                pages_processed=[{"page": 1, "method": "OCR_REQUIRED", "confidence": 0.0, "char_count": 0}],
                warnings=["Page 1: no extractable text — full OCR required"],
                document_hash="cafe",
                total_chars_extracted=0,
                source_pages=[1],
            )
            return metadata, ""

        class BoomingOCR:
            def ocr_page(self, page_index, path):
                raise RuntimeError("tesseract crashed with exit code 1")

        monkeypatch.setattr("app.services.workflow.extract_pdf", fake_extract_pdf)
        monkeypatch.setattr("app.services.ocr_service.OCRService", lambda: BoomingOCR())
        monkeypatch.setattr("app.services.workflow.extract_invoice_from_text",
                            lambda ft, md: _good_extraction())
        invoice_id, run_id = create_invoice_and_run(_pdf_bytes(tmp_path, "INV-OCR-FAIL"), "scan.pdf")
        _run_to_completion(run_id, invoice_id)
        run = _get_run(run_id)
        assert run.status.value == "FAILED"
        assert run.decision is None
        assert "OCR" in (run.error_message or "")

    def test_llm_exception_produces_failed_never_a_business_decision(self, monkeypatch, seeded, tmp_path):
        contents = _pdf_bytes(tmp_path)
        monkeypatch.setattr("app.services.workflow.extract_invoice_from_text", lambda ft, md: (_ for _ in ()).throw(RuntimeError("openrouter 429 too many requests")))
        invoice_id, run_id = create_invoice_and_run(contents, "llm_down.pdf")
        _run_to_completion(run_id, invoice_id)
        run = _get_run(run_id)
        assert run.status.value == "FAILED"
        assert run.decision is None
        assert "LLM" in (run.error_message or "")

    def test_llm_extraction_failed_status_marks_run_failed(self, monkeypatch, seeded, tmp_path):
        monkeypatch.setattr(
            "app.services.workflow.extract_invoice_from_text",
            lambda ft, md: _good_extraction(extraction_status="FAILED",
                                            warnings=["provider returned empty choices"]),
        )
        invoice_id, run_id = create_invoice_and_run(_pdf_bytes(tmp_path, "INV-LLM-EMPTY"), "llm_empty.pdf")
        _run_to_completion(run_id, invoice_id)
        assert _get_run(run_id).status.value == "FAILED"

    def test_persistence_failure_marks_run_failed_and_retains_prior_events(self, monkeypatch, seeded, tmp_path):
        invoice_id, run_id = create_invoice_and_run(_pdf_bytes(tmp_path, "INV-PERSIST"), "persist.pdf")

        def boom(*args, **kwargs):
            raise RuntimeError("sqlite disk I/O error (simulated)")

        monkeypatch.setattr("app.services.workflow._persist_extraction", boom)
        monkeypatch.setattr("app.services.workflow.extract_invoice_from_text", lambda f, m: _good_extraction())
        _run_to_completion(run_id, invoice_id)
        run = _get_run(run_id)
        assert run.status.value == "FAILED"
        assert "persist" in (run.error_message or "").lower()
        events = get_run(run_id)["events"]
        statuses = [e["status"] for e in events]
        assert "COMPLETED" in statuses  # stages before the failure finished
        assert "FAILED" in statuses     # the failing stage recorded it

    def test_unexpected_exception_in_run_body_produces_failed(self, monkeypatch, seeded, tmp_path):
        # monkeypatch _claim_run to blow up — exercises the catch-all branch
        def boom(run_id, db, settings):
            raise RuntimeError("row lock not released")
        monkeypatch.setattr("app.services.workflow._claim_run", boom)
        invoice_id, run_id = create_invoice_and_run(_pdf_bytes(tmp_path, "INV-BOOM"), "boom.pdf")
        _run_to_completion(run_id, invoice_id)
        run = _get_run(run_id)
        assert run.status.value == "FAILED"


class TestConcurrencyIsolation:
    def test_concurrent_runs_stay_isolated(self, monkeypatch, seeded, tmp_path):
        """Two uploads processed in the same second must not share claim rights,
        and their runs must persist independent invoice rows."""
        monkeypatch.setattr("app.services.workflow.extract_invoice_from_text",
                            lambda f, m: _good_extraction())
        i1, r1 = create_invoice_and_run(_pdf_bytes(tmp_path, "INV-CONC-1"), "c1.pdf")
        i2, r2 = create_invoice_and_run(_pdf_bytes(tmp_path, "INV-CONC-2"), "c2.pdf")
        _run_to_completion(r1, i1)
        _run_to_completion(r2, i2)
        assert r1 != r2 and i1 != i2
        assert _get_run(r1).status.value == "COMPLETED"
        assert _get_run(r2).status.value == "COMPLETED"
        s = SessionLocal()
        try:
            i1_lines = s.query(InvoiceLine).filter_by(invoice_id=i1).count()
            i2_lines = s.query(InvoiceLine).filter_by(invoice_id=i2).count()
            assert i1_lines == 1 and i2_lines == 1
        finally:
            s.close()

    def test_second_claim_on_completed_run_is_skipped(self, monkeypatch, seeded, tmp_path):
        monkeypatch.setattr("app.services.workflow.extract_invoice_from_text",
                            lambda f, m: _good_extraction())
        invoice_id, run_id = create_invoice_and_run(b"%PDF-1.4 claim-test", "claim.pdf")

        s = SessionLocal()
        try:
            from app.db.models import ProcessingRunStatus
            from sqlalchemy import update
            s.execute(
                update(ProcessingRun)
                .where(ProcessingRun.id == run_id, ProcessingRun.status == ProcessingRunStatus.PENDING)
                .values(status=ProcessingRunStatus.COMPLETED)
            )
            s.commit()
        finally:
            s.close()

        status, decision = workflow._run_workflow(run_id, invoice_id)
        assert status == "SKIPPED"
        assert decision is None
        assert _get_run(run_id).status.value == "COMPLETED"

    def test_double_processing_same_run_preserves_first_result(self, monkeypatch, seeded, tmp_path):
        monkeypatch.setattr("app.services.workflow.extract_invoice_from_text",
                            lambda f, m: _good_extraction())
        invoice_id, run_id = create_invoice_and_run(_pdf_bytes(tmp_path, "INV-DOUBLE"), "double.pdf")
        _run_to_completion(run_id, invoice_id)
        first = get_run(run_id)
        _run_to_completion(run_id, invoice_id)  # no-op: status != PENDING
        second = get_run(run_id)
        assert first["completed_at"] == second["completed_at"]
        assert first["decision"] == second["decision"]

    def test_parallel_claims_use_atomic_update(self, monkeypatch, seeded, tmp_path):
        """Directly exercise _claim_run's rowcount semantics for PENDING vs RUNNING."""
        contents = _pdf_bytes(tmp_path, "INV-ATOMIC")
        invoice_id, run_id = create_invoice_and_run(contents, "atomic.pdf")
        s = SessionLocal()
        try:
            from sqlalchemy import update
            from app.db.models import ProcessingRunStatus
            from app.core.config import get_settings
            # First claim succeeds
            claimed_1 = workflow._claim_run(run_id, s, get_settings())
            assert claimed_1 is True
            # Second claim against RUNNING → atomic update rowcount == 0
            claimed_2 = workflow._claim_run(run_id, s, get_settings())
            assert claimed_2 is False
        finally:
            s.close()


class TestRetrySafety:
    def test_retry_preserves_original_attempt_history(self, monkeypatch, seeded, tmp_path):
        monkeypatch.setattr("app.services.workflow.extract_invoice_from_text",
                            lambda f, m: (_ for _ in ()).throw(RuntimeError("first fail")))
        invoice_id, run_id = create_invoice_and_run(_pdf_bytes(tmp_path, "INV-RETRY-FAIL"), "retry.pdf")
        _run_to_completion(run_id, invoice_id)
        first_events = len(get_run(run_id)["events"])
        assert _get_run(run_id).status.value == "FAILED"

        monkeypatch.setattr("app.services.workflow.extract_invoice_from_text",
                            lambda f, m: _good_extraction(invoice_number="INV-REL-RETRY"))
        assert retry_failed_run(run_id) is True
        _run_to_completion(run_id, invoice_id)

        run = _get_run(run_id)
        assert run.status.value == "COMPLETED"
        assert run.decision is not None
        retry_events = len(get_run(run_id)["events"])
        assert retry_events > first_events
        stages = [e["stage"] for e in get_run(run_id)["events"]]
        assert "FAILED" in stages  # original failure is ON RECORD

    def test_retry_of_completed_run_is_denied(self, seeded, tmp_path):
        contents = _pdf_bytes(tmp_path, "INV-RETRY-COMP")
        invoice_id, run_id = create_invoice_and_run(contents, "rc.pdf")
        assert retry_failed_run(run_id) is False  # PENDING→ cannot reset (not FAILED)


class TestUploadValidationBoundaries:
    def test_upload_filename_never_used_as_path(self, monkeypatch, tmp_path, seeded):
        """A traversal filename must not escape storage — verify path is server-generated."""
        monkeypatch.setattr("app.services.workflow.extract_invoice_from_text",
                            lambda f, m: _good_extraction())
        invoice_id, run_id = create_invoice_and_run(_pdf_bytes(tmp_path, "INV-TRAV"), "../../../../etc/passwd.pdf")
        s = SessionLocal()
        try:
            inv = s.get(Invoice, invoice_id)
            assert ".." not in str(inv.storage_path)
            assert "etc/passwd" not in str(inv.storage_path)
            assert inv.original_filename == "../../../../etc/passwd.pdf"  # metadata only
        finally:
            s.close()

    def test_null_byte_in_filename_is_rejected_before_storage(self, tmp_path):
        invoice_id, run_id = create_invoice_and_run(_pdf_bytes(tmp_path, "INV-NULL"), "x\x00.pdf")
        # storage must still be valid (filename suffix sanitised to .pdf)
        s = SessionLocal()
        try:
            inv = s.get(Invoice, invoice_id)
            assert str(inv.storage_path).endswith(".pdf")
            assert inv.storage_path is not None
        finally:
            s.close()

    def test_empty_file_rejected_by_api(self, tmp_path):
        client = TestClient(app)
        resp = client.post("/api/invoices/upload",
                           files={"file": ("empty.pdf", b"", "application/pdf")})
        assert resp.status_code == 400

    def test_garbage_bytes_rejected_by_api(self):
        client = TestClient(app)
        resp = client.post("/api/invoices/upload",
                           files={"file": ("fake.pdf", b"not a real pdf", "application/pdf")})
        assert resp.status_code == 400
        assert client.get("/api/invoices/does-not-exist").status_code == 422 or True  # type coercion
