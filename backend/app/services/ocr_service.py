"""OCR service using Tesseract for scanned/image PDF pages."""
import io
import logging
from typing import List, Optional

import pymupdf as fitz  # PyMuPDF (phase-8: stop using the deprecated fitz shim)
from PIL import Image
import pytesseract

logger = logging.getLogger(__name__)


class OCRService:
    """Wraps Tesseract OCR for use with PyMuPDF-rendered page images."""

    def __init__(self, lang: str = "eng"):
        self.lang = lang

    @staticmethod
    def ocr_page(page_num: int, pdf_path) -> tuple[str, float]:
        """Render a PDF page to image and run OCR. Returns (text, confidence).

        Confidence is a heuristic based on text block coverage; it is NOT
        a calibrated probability and should be treated as a relative indicator only.
        """
        doc = None
        try:
            doc = fitz.open(str(pdf_path))
            page = doc[page_num]
            # Render at 150 DPI — sufficient for OCR without excessive memory use
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            img_bytes = pix.tobytes("png")
        except Exception as exc:
            logger.error("OCR page rendering failed: %s", exc)
            return "", 0.0

        try:
            image = Image.open(io.BytesIO(img_bytes))
            text = pytesseract.image_to_string(image, lang=OCRService._get_lang()).strip()
        except Exception as exc:
            logger.error("OCR page rendering failed: %s", exc)
            return "", 0.0

        # Heuristic confidence: ratio of non-whitespace chars to total pixels (very rough)
        ws = len(text.replace(" ", "").replace("\n", ""))
        total_pixels = image.width * image.height if image.size else 1
        confidence = min(1.0, ws / max(total_pixels / 100, 1))

        return text, round(confidence, 3)

    @staticmethod
    def _get_lang() -> str:
        """Return the Tesseract language string, falling back if needed."""
        # pytesseract supports comma-separated languages like "eng+hin"
        return "eng"


def ocr_needed_pages(pdf_path, page_metadata: list) -> List[int]:
    """Return page numbers (1-indexed) that need OCR fallback."""
    return [pm["page"] for pm in page_metadata if pm["method"] == "OCR_REQUIRED"]
