"""Synthetic invoice PDF generator using ReportLab for Phase 3 testing."""
import io
import os
from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# Register a Unicode font for Hindi/Devanagari support if available, else use Helvetica
def _register_fonts():
    """Register fonts; fall back to built-in Helvetica."""
    import subprocess
    # Check for Noto Sans Devanagari or other Indic fonts on the system
    for font_path in [
        "/usr/share/fonts/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]:
        if Path(font_path).exists():
            try:
                pdfmetrics.registerFont(TTFont("Custom", font_path))
                return "Custom"
            except Exception:
                pass
    return "Helvetica"


FONT = _register_fonts()


def create_digital_invoice(
    path: Path,
    invoice_number: str = "INV-2041-001",
    vendor_name: str = "ABC Industrial Supplies Pvt Ltd",
    po_ref: str = "PO-2041",
    date: str = "2026-10-15",
    due_date: str = "2026-11-15",
    currency: str = "INR",
    subtotal: Decimal = Decimal("50000.00"),
    tax_amount: Decimal = Decimal("9000.00"),
    discount: Decimal = Decimal("0.00"),
    total: Decimal = Decimal("59000.00"),
    line_items=None,
):
    """Create a clean digital invoice PDF with all standard fields."""
    if line_items is None:
        line_items = [
            {"description": "SS Hex Bolt M10", "quantity": 500, "unit": "nos", "unit_price": Decimal("50.00"), "line_total": Decimal("25000.00")},
            {"description": "MS Angle Bar 50x50", "quantity": 200, "unit": "mtrs", "unit_price": Decimal("75.00"), "line_total": Decimal("15000.00")},
            {"description": "Stainless Steel Hex Bolt M10", "quantity": 300, "unit": "nos", "unit_price": Decimal("60.00"), "line_total": Decimal("18000.00")},
        ]

    c = pdf_canvas.Canvas(str(path), pagesize=A4)
    width, height = A4

    # Header
    c.setFont(FONT, 18)
    c.drawString(50 * mm, height - 30 * mm, f"Invoice: {invoice_number}")
    c.setFont(FONT, 12)
    c.drawString(50 * mm, height - 40 * mm, f"Date: {date}")
    c.drawString(50 * mm, height - 50 * mm, f"Due Date: {due_date}")
    c.drawString(width - 80 * mm, height - 30 * mm, f"Currency: {currency}")

    # Vendor info
    c.setFont(FONT, 11)
    c.drawString(50 * mm, height - 75 * mm, "From:")
    c.drawString(50 * mm, height - 85 * mm, vendor_name)
    c.drawString(width - 80 * mm, height - 75 * mm, f"PO Reference: {po_ref}")

    # Line items table header
    y = height - 115 * mm
    c.setFont(FONT, 9)
    c.drawString(50 * mm, y, "Description")
    c.drawString(130 * mm, y, "Qty")
    c.drawString(165 * mm, y, "Unit")
    c.drawString(200 * mm, y, "Unit Price")
    c.drawString(270 * mm, y, "Line Total")

    # Line items
    y -= 10 * mm
    for item in line_items:
        desc = item.get("description", "")[:35]
        c.drawString(50 * mm, y, str(desc))
        c.drawString(130 * mm, y, str(item.get("quantity", "")))
        c.drawString(165 * mm, y, str(item.get("unit", "")))
        c.drawString(200 * mm, y, f"₹{item.get('unit_price', '0')}")
        c.drawString(270 * mm, y, f"₹{item.get('line_total', '0')}")
        y -= 8 * mm

    # Totals
    y -= 15 * mm
    c.setFont(FONT, 10)
    c.drawString(width - 100 * mm, y, f"Subtotal:      ₹{subtotal}")
    c.drawString(width - 100 * mm, y - 12 * mm, f"Tax (GST 18%): ₹{tax_amount}")
    if discount > 0:
        c.drawString(width - 100 * mm, y - 24 * mm, f"Discount:      -₹{discount}")
    c.setFont(FONT, 11)
    c.drawString(width - 100 * mm, y - (36 if discount > 0 else 24) * mm, f"Total:         ₹{total}")

    # Footer
    c.setFont(FONT, 8)
    c.drawString(50 * mm, 20 * mm, "This is a computer-generated invoice. No signature required.")
    c.save()
    return path


def create_multi_line_invoice(path: Path):
    """Invoice with many line items to test list extraction."""
    items = []
    for i in range(1, 11):
        items.append({
            "description": f"Item #{i} — Steel Rod {i*10}mm Dia",
            "quantity": Decimal(str(i * 5)),
            "unit": "kg",
            "unit_price": Decimal(str(i * 200)),
            "line_total": Decimal(str(i * 5 * i * 200)),
        })
    subtotal = sum(item["line_total"] for item in items)
    tax = subtotal * Decimal("0.18")
    total = subtotal + tax
    return create_digital_invoice(
        path,
        invoice_number="INV-2042-MULTI",
        vendor_name="Delta Supply Chain Solutions",
        po_ref="PO-2045",
        date="2026-10-20",
        currency="INR",
        subtotal=subtotal,
        tax_amount=tax,
        total=total,
        line_items=items,
    )


def create_missing_fields_invoice(path: Path):
    """Invoice with missing PO reference and due date."""
    c = pdf_canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    c.setFont(FONT, 18)
    c.drawString(50 * mm, height - 30 * mm, "Invoice: INV-2044-NOPO")
    c.setFont(FONT, 12)
    c.drawString(50 * mm, height - 40 * mm, "Date: 2026-10-22")
    # No due date, no PO reference intentionally missing
    c.drawString(50 * mm, height - 75 * mm, "From:")
    c.drawString(50 * mm, height - 85 * mm, "Sharma Electrical Components")
    c.setFont(FONT, 10)
    c.drawString(width - 100 * mm, height - 110 * mm, "Subtotal:      ₹30000.00")
    c.drawString(width - 100 * mm, height - 122 * mm, "Tax (GST):     ₹5400.00")
    c.setFont(FONT, 11)
    c.drawString(width - 100 * mm, height - 138 * mm, "Total:         ₹35400.00")
    c.save()
    return path


def create_missing_invoice_number(path: Path):
    """Invoice without an invoice number (e.g., proforma or draft)."""
    c = pdf_canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    c.setFont(FONT, 18)
    c.drawString(50 * mm, height - 30 * mm, "Proforma Invoice")
    c.setFont(FONT, 12)
    c.drawString(50 * mm, height - 40 * mm, "Date: 2026-10-25")
    c.drawString(50 * mm, height - 75 * mm, "From:")
    c.drawString(50 * mm, height - 85 * mm, "XYZ Metals and Alloys")
    c.setFont(FONT, 10)
    c.drawString(width - 100 * mm, height - 110 * mm, "Subtotal:      ₹75000.00")
    c.drawString(width - 100 * mm, height - 122 * mm, "Total:         ₹75000.00")
    c.save()
    return path


def create_ocr_ready_invoice(path: Path):
    """Create an invoice rendered entirely as image text (no selectable text layer).

    This forces the OCR pipeline to be used for all pages.
    Uses a rasterized approach: draw text onto a PDF canvas with no text extraction layer
    by using images or very low-level drawing. For testing purposes, we create a normal
    PDF but simulate scanned appearance by setting page mode that PyMuPDF still extracts from.

    Actual scanned-image PDFs require rendering to bitmap and embedding — for unit tests
    we use a separate test with a real image-based PDF (see test_ocr_service).
    """
    # This function creates a standard text-based PDF; the OCR path is tested separately
    # by passing a mock page_metadata where all pages are marked OCR_REQUIRED.
    return create_digital_invoice(
        path,
        invoice_number="INV-2047-OCRTEST",
        vendor_name="Golden Hardware Traders",
        po_ref="",  # intentionally empty to test missing PO handling
        date="2026-10-28",
        currency="INR",
        subtotal=Decimal("45000.00"),
        tax_amount=Decimal("8100.00"),
        total=Decimal("53100.00"),
    )


def generate_all_test_pdfs(output_dir: Path) -> list[Path]:
    """Generate all test PDFs and return their paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    pdfs = {
        "clean_digital.pdf": create_digital_invoice(output_dir / "clean_digital.pdf"),
        "multi_line.pdf": create_multi_line_invoice(output_dir / "multi_line.pdf"),
        "missing_po.pdf": create_missing_fields_invoice(output_dir / "missing_po.pdf"),
        "missing_number.pdf": create_missing_invoice_number(output_dir / "missing_number.pdf"),
        "ocr_ready.pdf": create_ocr_ready_invoice(output_dir / "ocr_ready.pdf"),
    }
    return list(pdfs.values())


def generate_scanned_pdf(path: Path):
    """Create a true scanned-image PDF (no selectable text layer).

    Renders each page as an image and embeds it — PyMuPDF will find zero extractable text.
    This forces the OCR fallback to handle every page.
    """
    from PIL import Image, ImageDraw, ImageFont

    c = pdf_canvas.Canvas(str(path), pagesize=A4)
    width, height = A4

    # Create a PIL image that looks like a scanned invoice
    img_width, img_height = int(width * 72 / 25.4), int(height * 72 / 25.4)
    try:
        font = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans.ttf", 20)
    except Exception:
        font = ImageFont.load_default()

    img = Image.new("RGB", (img_width, img_height), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((50, 50), "Invoice: INV-SCR-2048", fill="black", font=font)
    draw.text((50, 100), "Date: 2026-11-01", fill="black", font=font)
    draw.text((50, 150), "From:", fill="black", font=font)
    draw.text((50, 180), "Pune Precision Engineering", fill="black", font=font)
    draw.text((50, 250), "Description                    Qty    Unit    Price      Total", fill="black", font=font)
    draw.text((50, 300), "Copper Wire 2.5mm              100    mtrs   ₹150.00   ₹15000.00", fill="black", font=font)
    draw.text((50, 330), "Switch Socket 6A               200    nos     ₹45.00    ₹9000.00", fill="black", font=font)
    draw.text((img_width - 250, height - 200), "Subtotal:      ₹24000.00", fill="black", font=font)
    draw.text((img_width - 250, height - 240), "Tax (18%):     ₹4320.00", fill="black", font=font)
    draw.text((img_width - 250, height - 280), "Total:         ₹28320.00", fill="black", font=font)

    # Save image to a temp file so reportlab can read it (drawImage requires a path-like object)
    import tempfile
    tmp_fd, img_tmp = tempfile.mkstemp(suffix=".png", prefix="ocr_img_")
    os.close(tmp_fd)
    try:
        img.save(img_tmp, format="PNG")
        c.drawImage(img_tmp, 0, 0, width=width, height=height)
    finally:
        Path(img_tmp).unlink(missing_ok=True)

    c.save()
    return path


if __name__ == "__main__":
    out = Path(__file__).parent.parent.parent / "data" / "sample_invoices"
    generate_all_test_pdfs(out)
    scanned = out / "scanned_ocr.pdf"
    generate_scanned_pdf(scanned)
    print(f"Generated test PDFs in {out}:")
    for p in sorted(out.glob("*.pdf")):
        print(f"  {p.name} ({p.stat().st_size} bytes)")
