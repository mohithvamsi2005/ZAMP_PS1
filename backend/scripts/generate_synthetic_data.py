"""Generate synthetic verification invoices and run live E2E verification.

Generates five realistic test PDFs matched against the seeded vendors/POs in
``backend/data/demo.db``:
  1. syn_01_clean_approve.pdf       — Clean invoice matching PO-2044 (V-001)
  2. syn_02_blocked_vendor.pdf      — Blocked vendor invoice on PO-2047 (V-004 -> REJECT)
  3. syn_03_overbilling.pdf         — Exceeds PO-2045 balance & qty (V-002 -> REVIEW)
  4. syn_04_scanned_ocr.pdf         — Image-only scanned PDF for Tesseract OCR + PO-2046 (V-005)
  5. syn_05_duplicate_copy.pdf      — Exact byte-for-byte duplicate of #1 (DOC_DUP_001 -> REJECT)

Usage:
    cd backend
    .venv/Scripts/python.exe scripts/generate_synthetic_data.py
    .venv/Scripts/python.exe scripts/generate_synthetic_data.py --verify
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas

BACKEND_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BACKEND_DIR / "data" / "synthetic_invoices"


def _draw_digital_invoice(
    path: Path,
    *,
    invoice_number: str,
    invoice_date: str,
    due_date: str,
    vendor_name: str,
    vendor_gst: str,
    po_reference: str,
    currency: str,
    line_items: list[tuple[str, str, str, str, str]],
    subtotal: str,
    tax_label: str,
    tax_amount: str,
    total_amount: str,
) -> Path:
    c = pdf_canvas.Canvas(str(path), pagesize=A4)
    _, height = A4

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, height - 22 * mm, "Tax Invoice")

    c.setFont("Helvetica", 11)
    y = height - 34 * mm
    header_lines = [
        f"Invoice Number: {invoice_number}",
        f"Invoice Date: {invoice_date}",
        f"Due Date: {due_date}",
        f"Currency: {currency}",
        f"Vendor Name: {vendor_name}",
        f"Vendor GST: {vendor_gst}",
        f"Purchase Order: {po_reference}",
    ]
    for line in header_lines:
        c.drawString(20 * mm, y, line)
        y -= 6.5 * mm

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Description")
    c.drawString(95 * mm, y, "Qty")
    c.drawString(115 * mm, y, "Unit")
    c.drawString(138 * mm, y, "Unit Price")
    c.drawString(168 * mm, y, "Line Total")

    y -= 6 * mm
    c.setFont("Helvetica", 10)
    for desc, qty, unit, price, total in line_items:
        c.drawString(20 * mm, y, desc)
        c.drawString(95 * mm, y, qty)
        c.drawString(115 * mm, y, unit)
        c.drawString(138 * mm, y, price)
        c.drawString(168 * mm, y, total)
        y -= 6 * mm

    y -= 8 * mm
    c.setFont("Helvetica", 11)
    c.drawString(125 * mm, y, f"Subtotal: {subtotal}")
    y -= 6.5 * mm
    c.drawString(125 * mm, y, f"{tax_label}: {tax_amount}")
    y -= 6.5 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(125 * mm, y, f"Total: {total_amount}")

    c.setFont("Helvetica", 8)
    c.drawString(20 * mm, 18 * mm, "Synthetic verification invoice generated for Zamp Invoice Intelligence.")
    c.save()
    return path


def _load_scan_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        r"C:\Windows\Fonts\consola.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _draw_scanned_invoice(path: Path) -> Path:
    """Create a crisp rasterized image-only PDF (zero selectable text layer)."""
    width_pt, height_pt = A4
    dpi = 200
    img_w = int(width_pt / 72.0 * dpi)
    img_h = int(height_pt / 72.0 * dpi)

    img = Image.new("RGB", (img_w, img_h), color="white")
    draw = ImageDraw.Draw(img)
    font_title = _load_scan_font(44)
    font_body = _load_scan_font(28)

    lines = [
        ("Tax Invoice (Scanned Copy)", font_title, 90, 90),
        ("Invoice Number: INV-SYN-2026-004", font_body, 90, 180),
        ("Invoice Date: 2026-11-10", font_body, 90, 230),
        ("Currency: INR", font_body, 90, 280),
        ("Vendor Name: Golden Hardware Traders", font_body, 90, 330),
        ("Vendor GST: 29AABCG9876H1Z2", font_body, 90, 380),
        ("Purchase Order: PO-2046", font_body, 90, 430),
        ("Description              Qty    Unit   Unit Price   Line Total", font_body, 90, 520),
        ("Nuts M10                 1000   pcs    10.00        10000.00", font_body, 90, 580),
        ("Washers M10              1000   pcs    5.00         5000.00", font_body, 90, 635),
        ("Subtotal: 15000.00", font_body, 900, 760),
        ("Tax (0%): 0.00", font_body, 900, 815),
        ("Total: 15000.00", font_body, 900, 870),
    ]
    for text, fnt, x, y in lines:
        draw.text((x, y), text, fill="black", font=fnt)

    tmp_fd, tmp_png = tempfile.mkstemp(suffix=".png", prefix="zamp_scan_")
    os.close(tmp_fd)
    try:
        img.save(tmp_png, format="PNG")
        c = pdf_canvas.Canvas(str(path), pagesize=A4)
        c.drawImage(tmp_png, 0, 0, width=width_pt, height=height_pt)
        c.save()
    finally:
        Path(tmp_png).unlink(missing_ok=True)
    return path


def generate_all(output_dir: Path = OUT_DIR) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    p1 = _draw_digital_invoice(
        output_dir / "syn_01_clean_approve.pdf",
        invoice_number="INV-SYN-2026-001",
        invoice_date="2026-11-10",
        due_date="2026-12-10",
        vendor_name="ABC Industrial Supplies Pvt Ltd",
        vendor_gst="27AABCA1234F1Z5",
        po_reference="PO-2044",
        currency="INR",
        line_items=[
            ("Welding electrodes 3.2mm", "200", "kg", "250.00", "50000.00"),
            ("Safety goggles, anti-fog", "100", "pcs", "100.00", "10000.00"),
        ],
        subtotal="60000.00",
        tax_label="Tax (0%)",
        tax_amount="0.00",
        total_amount="60000.00",
    )

    p2 = _draw_digital_invoice(
        output_dir / "syn_02_blocked_vendor.pdf",
        invoice_number="INV-SYN-2026-002",
        invoice_date="2026-11-10",
        due_date="2026-12-10",
        vendor_name="Sharma Electrical Components",
        vendor_gst="07AAQCS1234E1Z8",
        po_reference="PO-2047",
        currency="INR",
        line_items=[
            ("LED panel light 30W", "50", "pcs", "600.00", "30000.00"),
        ],
        subtotal="30000.00",
        tax_label="Tax (0%)",
        tax_amount="0.00",
        total_amount="30000.00",
    )

    p3 = _draw_digital_invoice(
        output_dir / "syn_03_overbilling.pdf",
        invoice_number="INV-SYN-2026-003",
        invoice_date="2026-11-10",
        due_date="2026-12-10",
        vendor_name="XYZ Metals and Alloys",
        vendor_gst="27AABBX5678D1Z3",
        po_reference="PO-2045",
        currency="INR",
        line_items=[
            ("Aluminum angle section 50x50", "80", "pieces", "600.00", "48000.00"),
            ("Steel channel 75mm", "150", "pieces", "550.00", "82500.00"),
        ],
        subtotal="130500.00",
        tax_label="Tax (0%)",
        tax_amount="0.00",
        total_amount="130500.00",
    )

    p4 = _draw_scanned_invoice(output_dir / "syn_04_scanned_ocr.pdf")

    p5 = output_dir / "syn_05_duplicate_copy.pdf"
    shutil.copyfile(p1, p5)

    return [p1, p2, p3, p4, p5]


def verify_live(base_url: str, files: list[Path]) -> int:
    import httpx

    sys.path.insert(0, str(BACKEND_DIR))
    from app.core.config import get_settings

    settings = get_settings()
    headers = {}
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        status_resp = client.get("/api/auth/status")
        status_resp.raise_for_status()
        if status_resp.json().get("required"):
            password = settings.auth_password
            if not password:
                print("ERROR: auth required by server, but AUTH_PASSWORD not found in backend/.env")
                return 2
            login_resp = client.post("/api/auth/login", json={"password": password})
            login_resp.raise_for_status()
            print(f"Authenticated with {base_url} (cookie session)")

        results = []
        for pdf_path in files:
            with open(pdf_path, "rb") as fh:
                up = client.post(
                    "/api/invoices/upload",
                    files={"file": (pdf_path.name, fh, "application/pdf")},
                    headers=headers,
                )
            if up.status_code != 202:
                print(f"UPLOAD FAILED for {pdf_path.name}: {up.status_code} {up.text}")
                results.append((pdf_path.name, "UPLOAD_ERR", None, None, []))
                continue
            run_id = up.json()["run_id"]
            print(f"Uploaded {pdf_path.name} -> run_id={run_id}")

            deadline = time.time() + 180.0
            detail = None
            while time.time() < deadline:
                r = client.get(f"/api/runs/{run_id}")
                r.raise_for_status()
                detail = r.json()
                if detail["status"] in ("COMPLETED", "FAILED"):
                    break
                time.sleep(1.5)

            if detail is None or detail["status"] not in ("COMPLETED", "FAILED"):
                results.append((pdf_path.name, "TIMEOUT", None, run_id, []))
                continue

            stages = {ev["stage"]: ev["status"] for ev in detail.get("events", [])}
            dec = detail.get("decision_result") or {}
            rules = [
                f"{re['rule_id']}:{re['status']}"
                for re in dec.get("rules_evaluated", [])
                if re.get("status") != "PASS"
            ]
            if not rules:
                rules = [f"{re['rule_id']}:{re['status']}" for re in dec.get("rules_evaluated", [])[:3]]
            results.append((
                pdf_path.name,
                detail["status"],
                detail.get("decision"),
                run_id,
                {
                    "ocr": stages.get("OCR_PROCESSING"),
                    "llm_inv": (detail.get("extraction") or {}).get("invoice_number"),
                    "vendor": (detail.get("vendor_match") or {}).get("status"),
                    "po": (detail.get("po_match") or {}).get("status"),
                    "dup": (detail.get("duplicate_check") or {}).get("status"),
                    "amount": (detail.get("amount_validation") or {}).get("status"),
                    "rules": rules,
                    "err": detail.get("error_message"),
                },
            ))

        summary = client.get("/api/dashboard/summary").json()
        print("\n=== LIVE E2E VERIFICATION RESULTS ===")
        for name, status, decision, run_id, info in results:
            print(f"- {name}: status={status}, decision={decision}, info={info}")
        print("\n=== DASHBOARD SUMMARY ===")
        print(f"totals={summary.get('totals')}, decisions={summary.get('decisions')}, approval_rate={summary.get('approval_rate')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="Upload generated PDFs to the running server and print outcomes")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Server base URL")
    args = parser.parse_args()

    files = generate_all()
    print(f"Generated {len(files)} synthetic invoices in {OUT_DIR}:")
    for f in files:
        print(f"  {f.name} ({f.stat().st_size} bytes)")

    if args.verify:
        return verify_live(args.url, files)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
