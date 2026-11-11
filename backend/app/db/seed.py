"""
Seed script for synthetic procurement data.

Usage:
    cd backend
    .venv/bin/python -m app.db.seed

Idempotent: safe to run repeatedly. Existing records are preserved.
"""

import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone

# Ensure the project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db.session import engine, SessionLocal, init_db, enable_sqlite_foreign_keys
from app.db.models import (
    Base, Vendor, VendorStatus, PurchaseOrder, POStatus,
    PurchaseOrderLine, Invoice, InvoiceLine, ProcessingRun,
    ProcessingRunStatus, RunEventStatus,
)


def seed():
    init_db()
    fk_db = SessionLocal()
    try:
        enable_sqlite_foreign_keys(fk_db)
    finally:
        fk_db.close()

    db = SessionLocal()
    try:
        inserted = {"vendors": 0, "pos": 0, "po_lines": 0, "invoices": 0, "inv_lines": 0, "runs": 0}

        # ── Vendors ────────────────────────────────────────────────────────
        vendors_data = [
            {
                "vendor_code": "V-001",
                "legal_name": "ABC Industrial Supplies Pvt Ltd",
                "normalized_name": "abc industrial supplies pvt ltd",
                "tax_id": "27AABCA1234F1Z5",
                "country": "IN",
                "default_currency": "INR",
                "status": VendorStatus.ACTIVE,
            },
            {
                "vendor_code": "V-002",
                "legal_name": "XYZ Metals and Alloys",
                "normalized_name": "xyz metals and alloys",
                "tax_id": "27AABBX5678D1Z3",
                "country": "IN",
                "default_currency": "INR",
                "status": VendorStatus.ACTIVE,
            },
            {
                "vendor_code": "V-003",
                "legal_name": "Delta Supply Chain Solutions",
                "normalized_name": "delta supply chain solutions",
                "tax_id": None,
                "country": "IN",
                "default_currency": "INR",
                "status": VendorStatus.ACTIVE,
            },
            {
                "vendor_code": "V-004",
                "legal_name": "Sharma Electrical Components",
                "normalized_name": "sharma electrical components",
                "tax_id": "07AAQCS1234E1Z8",
                "country": "IN",
                "default_currency": "INR",
                "status": VendorStatus.BLOCKED,
            },
            {
                "vendor_code": "V-005",
                "legal_name": "Golden Hardware Traders",
                "normalized_name": "golden hardware traders",
                "tax_id": "29AABCG9876H1Z2",
                "country": "IN",
                "default_currency": "INR",
                "status": VendorStatus.ACTIVE,
            },
            {
                "vendor_code": "V-006",
                "legal_name": "Pune Precision Engineering",
                "normalized_name": "pune precision engineering",
                "tax_id": "27AABCP5555K1Z9",
                "country": "IN",
                "default_currency": "INR",
                "status": VendorStatus.INACTIVE,
            },
        ]

        existing_codes = {v["vendor_code"] for v in vendors_data}
        for code in existing_codes:
            exists = db.query(Vendor).filter_by(vendor_code=code).first()
            if not exists:
                v = Vendor(**vendors_data[[d["vendor_code"] for d in vendors_data].index(code)])
                db.add(v)
                inserted["vendors"] += 1

        db.flush()

        vendor_map = {v.vendor_code: v for v in db.query(Vendor).all()}

        # ── Purchase Orders ────────────────────────────────────────────────
        pos_data = [
            {"po_number": "PO-2041", "vendor_code": "V-001", "total_amount": Decimal("100000.00"), "status": POStatus.OPEN},
            {"po_number": "PO-2042", "vendor_code": "V-002", "total_amount": Decimal("75000.00"), "status": POStatus.OPEN},
            {"po_number": "PO-2043", "vendor_code": "V-003", "total_amount": Decimal("250000.00"), "status": POStatus.CLOSED},
            {"po_number": "PO-2044", "vendor_code": "V-001", "total_amount": Decimal("60000.00"), "status": POStatus.OPEN},
            {"po_number": "PO-2045", "vendor_code": "V-002", "total_amount": Decimal("120000.00"), "status": POStatus.OPEN},
            {"po_number": "PO-2046", "vendor_code": "V-005", "total_amount": Decimal("45000.00"), "status": POStatus.OPEN},
            {"po_number": "PO-2047", "vendor_code": "V-004", "total_amount": Decimal("30000.00"), "status": POStatus.OPEN},  # blocked vendor
            {"po_number": "PO-2048", "vendor_code": "V-006", "total_amount": Decimal("85000.00"), "status": POStatus.CLOSED},  # inactive vendor
        ]

        for po_d in pos_data:
            exists = db.query(PurchaseOrder).filter_by(po_number=po_d["po_number"]).first()
            if not exists:
                vendor = vendor_map[po_d["vendor_code"]]
                po = PurchaseOrder(
                    po_number=po_d["po_number"],
                    vendor_id=vendor.id,
                    issue_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
                    currency="INR",
                    total_amount=po_d["total_amount"],
                    status=po_d["status"],
                )
                db.add(po)
                inserted["pos"] += 1

        db.flush()
        po_map = {po.po_number: po for po in db.query(PurchaseOrder).all()}

        # ── PO Line Items ──────────────────────────────────────────────────
        po_lines_data = {
            "PO-2041": [
                ("Steel sheets, grade 304", "SS-304-6", Decimal("100"), "sheets", Decimal("500.00"), Decimal("50000.00")),
                ("Stainless steel fasteners, M8x25", "FAST-M8-25", Decimal("200"), "pcs", Decimal("75.00"), Decimal("15000.00")),
                ("Industrial adhesive sealant 5L", "SEAL-5L", Decimal("40"), "tins", Decimal("625.00"), Decimal("25000.00")),
            ],
            "PO-2042": [
                ("Copper wire, 2.5mm gauge", "CW-2.5", Decimal("500"), "meters", Decimal("80.00"), Decimal("40000.00")),
                ("PVC conduit pipe 25mm", "PVC-25", Decimal("300"), "meters", Decimal("50.00"), Decimal("15000.00")),
                ("Wire termination connectors", "CONN-TYPE-A", Decimal("400"), "pcs", Decimal("50.00"), Decimal("20000.00")),
            ],
            "PO-2043": [
                ("Industrial valve, 4-inch ball valve", "VALVE-BV-4", Decimal("20"), "units", Decimal("8500.00"), Decimal("170000.00")),
                ("Flange gasket set", "GASKET-FS", Decimal("50"), "sets", Decimal("1600.00"), Decimal("80000.00")),
            ],
            "PO-2044": [
                ("Welding electrodes 3.2mm", "ELEC-3.2", Decimal("200"), "kg", Decimal("250.00"), Decimal("50000.00")),
                ("Safety goggles, anti-fog", "GOGGLE-AF", Decimal("100"), "pcs", Decimal("100.00"), Decimal("10000.00")),
            ],
            "PO-2045": [
                ("Aluminum angle section 50x50", "AL-ANG-50", Decimal("80"), "pieces", Decimal("600.00"), Decimal("48000.00")),
                ("Steel channel 75mm", "CH-75", Decimal("60"), "pieces", Decimal("550.00"), Decimal("33000.00")),
                ("Mild steel plate 10mm", "MS-PLT-10", Decimal("20"), "sheets", Decimal("450.00"), Decimal("9000.00")),
                ("Surface treatment coating", "COAT-ST", Decimal("30"), "liters", Decimal("300.00"), Decimal("9000.00")),
            ],
            "PO-2046": [
                ("Hex bolts M10x50", "BOLT-M10-50", Decimal("1000"), "pcs", Decimal("25.00"), Decimal("25000.00")),
                ("Nuts M10", "NUT-M10", Decimal("1000"), "pcs", Decimal("10.00"), Decimal("10000.00")),
                ("Washers M10", "WSH-M10", Decimal("1000"), "pcs", Decimal("5.00"), Decimal("5000.00")),
                ("Lock washers M10", "LWSH-M10", Decimal("500"), "pcs", Decimal("8.00"), Decimal("4000.00")),
            ],
            "PO-2047": [
                ("LED panel light 30W", "LED-PNL-30", Decimal("50"), "pcs", Decimal("600.00"), Decimal("30000.00")),
            ],
            "PO-2048": [
                ("CNC milling cutter set", "CNC-CUTTER", Decimal("5"), "sets", Decimal("12000.00"), Decimal("60000.00")),
                ("Coolant fluid 20L", "COOL-20L", Decimal("3"), "drums", Decimal("5000.00"), Decimal("15000.00")),
            ],
        }

        for po_number, lines in po_lines_data.items():
            po = po_map[po_number]
            for desc, sku, qty, unit, price, total in lines:
                exists = db.query(PurchaseOrderLine).filter_by(
                    purchase_order_id=po.id, description=desc
                ).first()
                if not exists:
                    line = PurchaseOrderLine(
                        purchase_order_id=po.id,
                        description=desc,
                        sku=sku,
                        quantity=qty,
                        unit=unit,
                        unit_price=price,
                        line_total=total,
                    )
                    db.add(line)
                    inserted["po_lines"] += 1

        # ── Sample Invoices (no processing results — for Phase 3+ testing) ───
        invoices_data = [
            {
                "invoice_number": "INV-2026-1042",
                "vendor_code": "V-001",
                "po_number": "PO-2041",
                "currency": "INR",
                "subtotal": Decimal("50000.00"),
                "tax_amount": Decimal("9000.00"),
                "discount_amount": Decimal("0.00"),
                "total_amount": Decimal("59000.00"),
            },
            {
                "invoice_number": "INV-2026-1043",
                "vendor_code": "V-002",
                "po_number": "PO-2042",
                "currency": "INR",
                "subtotal": Decimal("40000.00"),
                "tax_amount": Decimal("7200.00"),
                "discount_amount": Decimal("0.00"),
                "total_amount": Decimal("47200.00"),
            },
            {
                "invoice_number": "INV-2026-1044",
                "vendor_code": "V-005",
                "po_number": "PO-2046",
                "currency": "INR",
                "subtotal": Decimal("25000.00"),
                "tax_amount": Decimal("4500.00"),
                "discount_amount": Decimal("0.00"),
                "total_amount": Decimal("29500.00"),
            },
        ]

        for inv_d in invoices_data:
            exists = db.query(Invoice).filter_by(invoice_number=inv_d["invoice_number"]).first()
            if not exists:
                vendor = vendor_map[inv_d["vendor_code"]]
                po = po_map.get(inv_d["po_number"])
                inv = Invoice(
                    invoice_number=inv_d["invoice_number"],
                    vendor_id=vendor.id,
                    purchase_order_id=po.id if po else None,
                    currency=inv_d["currency"],
                    subtotal=inv_d["subtotal"],
                    tax_amount=inv_d["tax_amount"],
                    discount_amount=inv_d["discount_amount"],
                    total_amount=inv_d["total_amount"],
                    invoice_date=datetime(2026, 10, 15, tzinfo=timezone.utc),
                )
                db.add(inv)
                inserted["invoices"] += 1

        db.flush()

        # Invoice line items for the sample invoices
        inv_lines_data = {
            "INV-2026-1042": [
                ("Steel sheets, grade 304", Decimal("100"), "sheets", Decimal("500.00"), Decimal("50000.00")),
            ],
            "INV-2026-1043": [
                ("Copper wire, 2.5mm gauge", Decimal("500"), "meters", Decimal("80.00"), Decimal("40000.00")),
            ],
            "INV-2026-1044": [
                ("Hex bolts M10x50", Decimal("1000"), "pcs", Decimal("25.00"), Decimal("25000.00")),
            ],
        }

        for inv_number, lines in inv_lines_data.items():
            inv = db.query(Invoice).filter_by(invoice_number=inv_number).first()
            if inv:
                for desc, qty, unit, price, total in lines:
                    exists = db.query(InvoiceLine).filter_by(
                        invoice_id=inv.id, description=desc
                    ).first()
                    if not exists:
                        line = InvoiceLine(
                            invoice_id=inv.id,
                            description=desc,
                            quantity=qty,
                            unit=unit,
                            unit_price=price,
                            line_total=total,
                        )
                        db.add(line)
                        inserted["inv_lines"] += 1

        # ── Processing runs (empty for now — created at runtime in Phase 6) ─
        # No processing runs seeded here; they are created dynamically.

        db.commit()

        print("Seeding complete:")
        for key, count in inserted.items():
            print(f"  {key}: {count} inserted")
        print(f"  Total: {sum(inserted.values())} records")

    except Exception as e:
        db.rollback()
        print(f"Seed failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
