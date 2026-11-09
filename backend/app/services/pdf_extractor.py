"""PDF document extraction using PyMuPDF with mixed-text/OCR fallback."""
import hashlib
import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

import pymupdf as fitz  # PyMuPDF (phase-8: stop using the deprecated fitz shim)

from app.schemas.invoice import ExtractionMetadata

logger = logging.getLogger(__name__)

# Minimum characters of extractable text to consider a page "text-rich"
TEXT_THRESHOLD_CHARS = 50


class PDFExtractionError(Exception):
    """Raised when PDF processing fails."""

    def __init__(self, message: str, document_hash: str = "", original_error=None):
        super().__init__(message)
        self.document_hash = document_hash
        self.original_error = original_error


def sha256_file(path: Path) -> str:
    """Calculate SHA-256 hash of a file without loading it entirely into memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_pdf(pdf_path: Path) -> Tuple[ExtractionMetadata, str]:
    """Extract text from a PDF using PyMuPDF.

    Returns (metadata, full_text) where metadata includes per-page extraction method info.
    Pages with insufficient text are marked for OCR fallback (see ocr_service).
    """
    if not pdf_path.exists():
        raise PDFExtractionError(f"PDF file not found: {pdf_path}")

    document_hash = sha256_file(pdf_path)

    doc = None
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        raise PDFExtractionError(
            f"Failed to open PDF: {exc}",
            document_hash=document_hash,
            original_error=exc,
        ) from exc

    pages_processed: List[dict] = []
    full_text_parts: List[str] = []
    warnings: List[str] = []
    total_chars = 0

    page_count = len(doc)

    for page_num in range(page_count):
        page = doc[page_num]
        text = page.get_text("text").strip()

        if len(text) >= TEXT_THRESHOLD_CHARS:
            method = "PDF_TEXT"
            confidence = min(1.0, len(text) / 2000.0)  # heuristic quality indicator
        else:
            method = "OCR_REQUIRED"
            confidence = 0.0
            if text:
                warnings.append(f"Page {page_num + 1}: low text yield ({len(text)} chars) — OCR recommended")
            else:
                warnings.append(f"Page {page_num + 1}: no extractable text — full OCR required")

        pages_processed.append({
            "page": page_num + 1,
            "method": method,
            "confidence": round(confidence, 3),
            "char_count": len(text),
        })
        full_text_parts.append(f"--- PAGE {page_num + 1} ---\n{text}")
        total_chars += len(text)

    doc.close()

    metadata = ExtractionMetadata(
        page_count=page_count,
        pages_processed=pages_processed,
        warnings=warnings,
        document_hash=document_hash,
        total_chars_extracted=total_chars,
    )

    return metadata, "\n".join(full_text_parts)


def validate_pdf(path: Path, max_upload_mb: int = 20) -> List[str]:
    """Validate a PDF file before processing. Returns list of warnings/errors."""
    errors: List[str] = []
    if not path.exists():
        return ["File does not exist"]
    if not path.name.lower().endswith(".pdf"):
        errors.append("File is not a PDF (extension mismatch)")
    max_bytes = max_upload_mb * 1024 * 1024
    size = path.stat().st_size
    if size > max_bytes:
        errors.append(f"File exceeds maximum size ({max_upload_mb} MB): {size / 1024 / 1024:.1f} MB")
    if size == 0:
        errors.append("File is empty")
    # Structural check: a real PDF always starts with the %PDF- header, so
    # garbage bytes (or a renamed HTML/text file) are rejected before storage.
    with open(path, "rb") as fh:
        magic = fh.read(8)
    if size > 0 and not magic.startswith(b"%PDF-"):
        errors.append("File is not a valid PDF (missing %PDF header — probably not a real PDF)")
    return errors
