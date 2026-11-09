"""Numeric pre-normalisation of LLM output — unit + integration tests.

Background: real-world LLM responses to Indian invoices routinely contain
"₹1,00,000.00", thousands separators, stray currency glyphs transcribed as a
leading letter (₹ → I), or the string "null".  Pydantic's decimal parsing is
strict and must stay strict, so the extractor normalises those values *before*
validation instead of weakening it.  These tests pin that contract.
"""
from decimal import Decimal

import pytest

from app.schemas.invoice import InvoiceExtraction
from app.services.llm_extractor import _clean_number, _normalise_numbers


class TestCleanNumber:
    @pytest.mark.parametrize("raw,expected", [
        ("60000.00", "60000.00"),
        ("I60000.00", "60000.00"),          # ₹ misread as leading letter
        ("₹1,00,000.00", "100000.00"),      # Indian lakh grouping
        ("1,00,000.00", "100000.00"),
        ("₹1,000.00", "1000.00"),
        ("$500", "500"),
        ("INR 250.00", "250.00"),
        ("  42,000  ", "42000"),
        ("-500.25", "-500.25"),
        ("null", None),
        ("None", None),
        ("N/A", None),
        ("", None),
        ("₹", None),
        ("—", None),
    ])
    def test_clean_number(self, raw, expected):
        assert _clean_number(raw) == expected

    def test_numbers_passthrough(self):
        assert _clean_number(42) == 42
        assert _clean_number(3.5) == 3.5
        assert _clean_number(None) is None


class TestNormaliseNumbers:
    def test_nested_fields_cleaned(self):
        raw = {
            "invoice_number": "INV-1",
            "subtotal": "₹50,000.00",
            "tax_amount": "9,000.00",
            "discount_amount": "null",
            "total_amount": "I59000.00",
            "currency": "INR",
            "line_items": [
                {"description": "Steel", "quantity": "1,00",
                 "unit_price": "I500.00", "line_total": "50,000.00"},
            ],
        }
        out = _normalise_numbers(raw)
        assert out["subtotal"] == "50000.00"
        assert out["tax_amount"] == "9000.00"
        assert out["discount_amount"] is None
        assert out["total_amount"] == "59000.00"
        assert out["currency"] == "INR"  # non-numeric field untouched
        assert out["line_items"][0]["quantity"] == "100"
        assert out["line_items"][0]["unit_price"] == "500.00"
        assert out["line_items"][0]["line_total"] == "50000.00"

    def test_messy_payload_passes_pydantic(self):
        """The exact failure mode seen in the live run must validate now."""
        raw = _normalise_numbers({
            "invoice_number": "INV-DEMO-1001",
            "po_reference": "PO-2044",
            "vendor_name": "ABC Industrial Supplies Pvt Ltd",
            "subtotal": "I60000.00",
            "tax_amount": "I0.00",
            "discount_amount": "null",
            "total_amount": "I60000.00",
            "line_items": [
                {"description": "Welding electrodes 3.2mm", "quantity": "200",
                 "unit": "kg", "unit_price": "I250.0", "line_total": "50,000.00"},
                {"description": "Safety goggles, anti-fog", "quantity": "100",
                 "unit": "pcs", "unit_price": "I100.0", "line_total": "10,000.00"},
            ],
            "extraction_status": "SUCCESS",
            "evidence": {},
            "warnings": [],
        })
        extraction = InvoiceExtraction(**raw)
        assert extraction.subtotal == Decimal("60000.00")
        assert extraction.tax_amount == Decimal("0.00")
        assert extraction.discount_amount is None
        assert extraction.total_amount == Decimal("60000.00")
        assert extraction.line_items[0].unit_price == Decimal("250.0")
        assert extraction.line_items[1].unit_price == Decimal("100.0")


class TestEndToEndProviderMock:
    def test_extract_succeeds_despite_messy_json(self, monkeypatch):
        """Full extract_invoice_from_text path with a messy provider — no
        network, Pydantic never sees raw junk."""
        messy = {
            "invoice_number": "INV-777",
            "currency": "INR",
            "po_reference": "PO-2044",
            "vendor_name": "ABC Industrial Supplies Pvt Ltd",
            "subtotal": "₹60,000.00",
            "tax_amount": "0.00",
            "discount_amount": "null",
            "total_amount": "I60000.00",
            "line_items": [],
            "evidence": {
                "total_amount": {"text": "₹60,000.00", "page": 1, "confidence": 0.9},
            },
            "extraction_status": "SUCCESS",
            "warnings": [],
        }

        class FakeProvider:
            max_retries = 1
            model = "fake/free-model"

            def extract_invoice(self, system_message: str, user_message: str):
                return messy

        class FakeProviderType:
            pass

        monkeypatch.setattr(
            "app.services.llm_extractor._build_provider", lambda: FakeProvider()
        )
        from app.schemas.invoice import ExtractionMetadata
        from app.services.llm_extractor import extract_invoice_from_text

        metadata = ExtractionMetadata(
            page_count=1,
            pages_processed=[{"page": 1, "method": "PDF_TEXT", "confidence": 1.0, "char_count": 10}],
            warnings=[],
            document_hash="cafe",
            total_chars_extracted=10,
            source_pages=[1],
        )
        extraction = extract_invoice_from_text("any text", metadata)
        assert extraction.extraction_status == "SUCCESS"
        assert extraction.total_amount == Decimal("60000.00")
        assert extraction.warnings == []
