"""Phase 3 tests: PDF extraction, OCR, Pydantic schema, LLM providers, synthetic PDFs."""
import json
import hashlib
import io
import os
from decimal import Decimal
from pathlib import Path
from typing import Optional

import httpx
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.schemas.invoice import ExtractionMetadata, InvoiceExtraction, LineItem, FieldEvidence
from app.services.pdf_extractor import extract_pdf, validate_pdf, sha256_file, PDFExtractionError
from app.services.ocr_service import OCRService, ocr_needed_pages
from app.services.extraction_prompt import build_extraction_prompt
from app.services.llm_providers.base import ExtractionError, InvoiceExtractionProvider
from app.services.llm_providers.openrouter import OpenRouterProvider
from app.services.llm_providers.llama_cpp import LlamaCppProvider
from app.services.test_pdf_generator import (
    create_digital_invoice,
    create_multi_line_invoice,
    create_missing_fields_invoice,
    create_missing_invoice_number,
    generate_scanned_pdf,
)

TEST_PDF_DIR = Path(__file__).parent.parent.parent / "data" / "sample_invoices"


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _generate_test_pdfs():
    """Generate all synthetic test PDFs before the test session."""
    TEST_PDF_DIR.mkdir(parents=True, exist_ok=True)
    create_digital_invoice(TEST_PDF_DIR / "clean_digital.pdf")
    create_multi_line_invoice(TEST_PDF_DIR / "multi_line.pdf")
    create_missing_fields_invoice(TEST_PDF_DIR / "missing_po.pdf")
    create_missing_invoice_number(TEST_PDF_DIR / "missing_number.pdf")
    generate_scanned_pdf(TEST_PDF_DIR / "scanned_ocr.pdf")


@pytest.fixture
def mock_httpx_post(monkeypatch):
    """Return a function that returns httpx.Response with given JSON body and status."""
    def _make(json_body: dict, status_code: int = 200, headers: dict = None):
        raw = json.dumps(json_body).encode()
        resp = httpx.Response(status_code=status_code, content=raw, headers=headers or {"content-type": "application/json"})
        return resp

    return _make


# ── PDF Extraction Tests ───────────────────────────────────────────────────────

class TestPDFExtraction:
    def test_clean_digital_pdf_extraction(self):
        path = TEST_PDF_DIR / "clean_digital.pdf"
        assert path.exists(), f"Test PDF missing: {path}"
        metadata, text = extract_pdf(path)
        assert metadata.page_count == 1
        assert metadata.total_chars_extracted > 0
        assert any(pm["method"] == "PDF_TEXT" for pm in metadata.pages_processed)
        assert "INV-2041-001" in text
        assert "ABC Industrial Supplies" in text

    def test_multi_line_pdf_extraction(self):
        path = TEST_PDF_DIR / "multi_line.pdf"
        metadata, text = extract_pdf(path)
        assert metadata.page_count == 1
        assert "Item #1" in text
        assert "Item #10" in text

    def test_missing_fields_pdf_extracts_what_it_can(self):
        path = TEST_PDF_DIR / "missing_po.pdf"
        metadata, text = extract_pdf(path)
        assert metadata.page_count == 1
        assert "INV-2044-NOPO" in text
        # PO reference intentionally absent — text should not contain a PO number

    def test_missing_invoice_number_pdf(self):
        path = TEST_PDF_DIR / "missing_number.pdf"
        metadata, text = extract_pdf(path)
        assert metadata.page_count == 1
        assert "Proforma Invoice" in text
        # No invoice number field should be present as a standard format

    def test_scanned_pdf_zero_text_extraction(self):
        """Scanned (image-only) PDFs produce no selectable text — all pages marked OCR_REQUIRED."""
        path = TEST_PDF_DIR / "scanned_ocr.pdf"
        assert path.exists()
        metadata, text = extract_pdf(path)
        assert metadata.page_count >= 1
        # All pages should need OCR since the PDF was created as an image
        assert all(pm["method"] == "OCR_REQUIRED" for pm in metadata.pages_processed)
        assert metadata.total_chars_extracted == 0

    def test_sha256_hash_is_deterministic(self):
        path = TEST_PDF_DIR / "clean_digital.pdf"
        h1 = sha256_file(path)
        h2 = sha256_file(path)
        assert h1 == h2
        assert len(h1) == 64  # hex digest length

    def test_validate_pdf_rejects_non_pdf(self):
        tmp = Path("/tmp/not_a_pdf.txt")
        tmp.write_text("not a pdf")
        errors = validate_pdf(tmp, max_upload_mb=20)
        assert any("not a PDF" in e for e in errors)
        tmp.unlink()

    def test_validate_pdf_accepts_valid(self):
        path = TEST_PDF_DIR / "clean_digital.pdf"
        errors = validate_pdf(path, max_upload_mb=20)
        assert errors == []


# ── OCR Service Tests ──────────────────────────────────────────────────────────

class TestOCRService:
    def test_ocr_on_scanned_pdf(self):
        """OCR should extract text from the scanned PDF we generated."""
        path = TEST_PDF_DIR / "scanned_ocr.pdf"
        ocr = OCRService()
        text, confidence = ocr.ocr_page(0, path)
        # Should get some text since the scanned PDF contains rendered text
        assert len(text) > 0, "OCR returned empty text from scanned PDF"
        assert 0.0 <= confidence <= 1.0
        assert "INV-SCR-2048" in text or len(text) > 50  # at least partial success

    def test_ocr_needed_pages(self):
        pages = [
            {"page": 1, "method": "PDF_TEXT", "confidence": 0.9},
            {"page": 2, "method": "OCR_REQUIRED", "confidence": 0.0},
            {"page": 3, "method": "OCR", "confidence": 0.8},
        ]
        needed = ocr_needed_pages(None, pages)
        assert needed == [2]

    def test_ocr_returns_empty_on_bad_pdf(self):
        """OCR should not crash on an unreadable file."""
        ocr = OCRService()
        text, confidence = ocr.ocr_page(0, Path("/nonexistent/path.pdf"))
        assert text == ""
        assert confidence == 0.0


# ── Pydantic Schema Tests ──────────────────────────────────────────────────────

class TestInvoiceExtractionSchema:
    def test_valid_full_extraction(self):
        data = {
            "invoice_number": "INV-2041-001",
            "invoice_date": "2026-10-15",
            "due_date": "2026-11-15",
            "currency": "INR",
            "po_reference": "PO-2041",
            "vendor_name": "ABC Industrial Supplies Pvt Ltd",
            "vendor_tax_id": "27AABCU9603R1ZM",
            "subtotal": "50000.00",
            "tax_amount": "9000.00",
            "discount_amount": "0.00",
            "total_amount": "59000.00",
            "line_items": [
                {"description": "SS Hex Bolt M10", "quantity": 500, "unit": "nos", "unit_price": "50.00", "line_total": "25000.00"},
            ],
        }
        ext = InvoiceExtraction(**data)
        assert ext.invoice_number == "INV-2041-001"
        assert ext.subtotal == Decimal("50000.00")
        assert ext.total_amount == Decimal("59000.00")
        assert len(ext.line_items) == 1
        assert ext.line_items[0].quantity == Decimal("500")

    def test_all_null_fields(self):
        ext = InvoiceExtraction(extraction_status="PARTIAL", warnings=["No invoice number found"])
        assert ext.invoice_number is None
        assert ext.total_amount is None
        assert ext.warnings == ["No invoice number found"]

    def test_decimal_parsing_from_strings(self):
        data = {"total_amount": "12345.67", "line_items": [{"description": "Test", "quantity": "10", "unit_price": "99.99", "line_total": "999.90"}]}
        ext = InvoiceExtraction(**data)
        assert ext.total_amount == Decimal("12345.67")
        assert ext.line_items[0].quantity == Decimal("10")

    def test_line_item_parse_invalid_decimal(self):
        """Invalid decimal strings for quantity must be rejected by Pydantic V2 — garbage in, error out."""
        data = {"line_items": [{"description": "Bad", "quantity": "not-a-number", "unit_price": 10, "line_total": None}]}
        with pytest.raises(Exception):
            InvoiceExtraction(**data)

    def test_extraction_metadata(self):
        meta = ExtractionMetadata(
            page_count=3,
            pages_processed=[{"page": 1, "method": "PDF_TEXT", "confidence": 0.95}],
            warnings=["Page 2 needs OCR"],
            document_hash="abc123" * 8,
            total_chars_extracted=1200,
        )
        assert meta.page_count == 3
        assert meta.source_pages == []

    def test_to_json_safe_roundtrips_decimals(self):
        ext = InvoiceExtraction(
            invoice_number="T-001",
            subtotal=Decimal("99.99"),
            total_amount=Decimal("119.99"),
            line_items=[LineItem(description="Widget", quantity=Decimal("5"), unit_price=Decimal("20.00"), line_total=Decimal("100.00"))],
        )
        data = ext.to_json_safe()
        assert data["subtotal"] == "99.99"
        assert data["line_items"][0]["quantity"] == "5"


# ── LLM Provider Tests (mocked) ───────────────────────────────────────────────

class TestOpenRouterProvider:
    def test_successful_extraction(self, monkeypatch, mock_httpx_post):
        resp_body = {
            "choices": [{"message": {"content": json.dumps({
                "invoice_number": "INV-MOCK-001",
                "total_amount": "59000.00",
                "currency": "INR",
                "extraction_status": "SUCCESS",
            })}}],
        }
        monkeypatch.setattr("httpx.Client.post", lambda *a, **kw: mock_httpx_post(resp_body))
        provider = OpenRouterProvider(
            base_url="http://mock:9931/v1", api_key="key", model="test-model",
            timeout_seconds=5, max_retries=0,
        )
        result = provider.extract_invoice("sys", "usr")
        assert result["invoice_number"] == "INV-MOCK-001"

    def test_rate_limit_retry(self, monkeypatch, mock_httpx_post):
        call_count = [0]

        def fake_post(*a, **kw):
            call_count[0] += 1
            if call_count[0] <= 1:
                return httpx.Response(429, content=b"{}")
            body = {"choices": [{"message": {"content": json.dumps({"invoice_number": "INV-RTRY"})}}]}
            return mock_httpx_post(body)

        monkeypatch.setattr("httpx.Client.post", fake_post)
        provider = OpenRouterProvider(base_url="http://mock:1/v1", api_key="", model="m", timeout_seconds=5, max_retries=1)
        result = provider.extract_invoice("s", "u")
        assert result["invoice_number"] == "INV-RTRY"
        assert call_count[0] == 2

    def test_connection_failure_raises(self, monkeypatch):
        import httpx as _httpx
        monkeypatch.setattr("httpx.Client.post", lambda *a, **kw: (_ for _ in ()).throw(_httpx.HTTPError("boom")))
        provider = OpenRouterProvider(base_url="http://localhost:9999/v1", api_key="", model="m", timeout_seconds=0.01, max_retries=0)
        with pytest.raises(ExtractionError):
            provider.extract_invoice("s", "u")

    def test_nemotron_sets_reasoning_effort_none(self, monkeypatch, mock_httpx_post):
        captured = []

        def fake_post(self, url, json=None, headers=None, **kw):
            captured.append(json)
            body = {"choices": [{"message": {"content": "{\"invoice_number\": \"INV-N\"}"}}]}
            return mock_httpx_post(body)

        monkeypatch.setattr("httpx.Client.post", fake_post)
        nem = OpenRouterProvider(
            base_url="http://mock:1/v1", api_key="",
            model="nvidia/nemotron-3-ultra-550b-a55b:free", timeout_seconds=5, max_retries=0,
        )
        nem.extract_invoice("s", "u")
        other = OpenRouterProvider(
            base_url="http://mock:1/v1", api_key="",
            model="google/gemma-2-9b-it:free", timeout_seconds=5, max_retries=0,
        )
        other.extract_invoice("s", "u")
        assert captured[0].get("reasoning") == {"effort": "none"}
        assert "reasoning" not in captured[1]


class TestLlamaCppProvider:
    def test_successful_extraction(self, monkeypatch, mock_httpx_post):
        resp_body = {
            "choices": [{"message": {"content": json.dumps({
                "invoice_number": "INV-LC-001",
                "total_amount": "35400.00",
                "currency": "INR",
                "extraction_status": "SUCCESS",
            })}}],
        }
        monkeypatch.setattr("httpx.Client.post", lambda *a, **kw: mock_httpx_post(resp_body))
        provider = LlamaCppProvider(
            base_url="http://mock:8080/v1", api_key="", model="llama-model",
            timeout_seconds=5, max_retries=0,
        )
        result = provider.extract_invoice("sys", "usr")
        assert result["invoice_number"] == "INV-LC-001"

    def test_non_json_response_raises(self, monkeypatch):
        monkeypatch.setattr("httpx.Client.post", lambda *a, **kw: httpx.Response(200, content=b"not json"))
        provider = LlamaCppProvider(base_url="http://localhost:8080/v1", api_key="", model="m", timeout_seconds=5, max_retries=0)
        with pytest.raises(ExtractionError):
            provider.extract_invoice("s", "u")


# ── Prompt Builder Tests ───────────────────────────────────────────────────────

class TestExtractionPrompt:
    def test_build_prompt_contains_invoice_text(self):
        msgs = build_extraction_prompt("Invoice #123 from Vendor X total ₹59000")
        assert "system" in msgs and "user" in msgs
        assert "Invoice #123" in msgs["user"]

    def test_prompt_includes_model_name(self):
        msgs = build_extraction_prompt("test", model_name="llama-3.2-3b")
        assert "llama-3.2-3b" in msgs["system"]


# ── LLM Extractor Tests (mocked provider) ─────────────────────────────────────

class TestLLMExtractor:
    def test_extract_with_mock_provider(self, monkeypatch):
        mock_response = {
            "invoice_number": "INV-TEST-001",
            "invoice_date": "2026-10-15",
            "currency": "INR",
            "subtotal": "40000.00",
            "tax_amount": "7200.00",
            "total_amount": "47200.00",
            "line_items": [{"description": "Cable 2.5mm", "quantity": 100, "unit": "mtrs", "unit_price": "40.00", "line_total": "4000.00"}],
        }

        class FakeProvider(InvoiceExtractionProvider):
            def extract_invoice(self, system_message, user_message):
                return mock_response

        monkeypatch.setattr("app.services.llm_extractor._build_provider", lambda: FakeProvider("", "", ""))

        from app.services.llm_extractor import extract_invoice_from_text
        metadata = ExtractionMetadata(page_count=1, pages_processed=[{"page": 1, "method": "PDF_TEXT", "confidence": 0.9}], warnings=[], document_hash="x" * 64, total_chars_extracted=500)

        result = extract_invoice_from_text("test text", metadata)
        assert result.invoice_number == "INV-TEST-001"
        assert result.total_amount == Decimal("47200.00")
        assert len(result.line_items) == 1

    def test_extract_no_provider(self, monkeypatch):
        monkeypatch.setattr("app.services.llm_extractor._build_provider", lambda: None)
        from app.services.llm_extractor import extract_invoice_from_text
        metadata = ExtractionMetadata(page_count=1, pages_processed=[], warnings=[], document_hash="x" * 64, total_chars_extracted=0)
        result = extract_invoice_from_text("test", metadata)
        assert result.extraction_status == "FAILED"


# ── Full Pipeline Tests (PDF extraction only — no LLM call) ───────────────────

class TestFullPipeline:
    def test_digital_pdf_to_metadata(self):
        from app.services.llm_extractor import extract_invoice
        path = TEST_PDF_DIR / "clean_digital.pdf"
        # Call with a dummy ocr_service so we don't trigger actual LLM calls
        from app.services.ocr_service import OCRService
        extraction, metadata = extract_invoice(path, ocr_service=OCRService())
        assert metadata.page_count == 1
        assert metadata.total_chars_extracted > 0

    def test_scanned_pdf_triggers_ocr(self):
        from app.services.llm_extractor import extract_invoice
        path = TEST_PDF_DIR / "scanned_ocr.pdf"
        ocr = OCRService()
        extraction, metadata = extract_invoice(path, ocr_service=ocr)
        # After LLM call (which will fail since no provider is configured), metadata should reflect OCR pages
        assert any(pm["method"] == "OCR" for pm in metadata.pages_processed), \
            f"Expected OCR method but got: {[pm['method'] for pm in metadata.pages_processed]}"
