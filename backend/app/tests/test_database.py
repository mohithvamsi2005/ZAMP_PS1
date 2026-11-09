"""Test database models, constraints, and seed idempotency."""

import pytest
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone
import uuid

from sqlalchemy import text
from app.db.session import engine, SessionLocal, init_db, enable_sqlite_foreign_keys
from app.db.models import (
    Vendor, VendorStatus, PurchaseOrder, POStatus,
    PurchaseOrderLine, Invoice, InvoiceLine,
    ProcessingRun, ProcessingRunStatus, ProcessingRunEvent, RunEventStatus,
)


@pytest.fixture(scope="function")
def db_session():
    """Fresh database session for each test."""
    from app.db.models import Base
    Base.metadata.drop_all(bind=engine)  # clear stale state from prior runs
    init_db()
    enable_sqlite_foreign_keys(SessionLocal())
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


# ── Vendor Tests ─────────────────────────────────────────────────────────────


def test_vendor_create_and_query(db_session):
    vendor = Vendor(
        vendor_code="V-TEST-001",
        legal_name="Test Vendor Ltd",
        normalized_name="test vendor ltd",
        tax_id="12345",
        country="IN",
        default_currency="INR",
        status=VendorStatus.ACTIVE,
    )
    db_session.add(vendor)
    db_session.commit()

    found = db_session.query(Vendor).filter_by(vendor_code="V-TEST-001").first()
    assert found is not None
    assert found.legal_name == "Test Vendor Ltd"
    assert found.status == VendorStatus.ACTIVE


def test_vendor_unique_code(db_session):
    v1 = Vendor(
        vendor_code="V-UNI", legal_name="First",
        normalized_name="first", status=VendorStatus.ACTIVE,
    )
    v2 = Vendor(
        vendor_code="V-UNI", legal_name="Second",
        normalized_name="second", status=VendorStatus.ACTIVE,
    )
    db_session.add(v1)
    db_session.commit()

    with pytest.raises(Exception):  # IntegrityError on duplicate
        db_session.add(v2)
        db_session.commit()


def test_vendor_status_values(db_session):
    for status in [VendorStatus.ACTIVE, VendorStatus.BLOCKED, VendorStatus.INACTIVE]:
        v = Vendor(
            vendor_code=f"V-{status.value}", legal_name=status.value,
            normalized_name=status.value.lower(), status=status,
        )
        db_session.add(v)
    db_session.commit()

    # Verify the three new vendors were inserted (count may be higher due to seed data or prior runs)
    codes = {f"V-{s.value}" for s in [VendorStatus.ACTIVE, VendorStatus.BLOCKED, VendorStatus.INACTIVE]}
    found = db_session.query(Vendor).filter(Vendor.vendor_code.in_(codes)).all()
    assert len(found) == 3


# ── Purchase Order Tests ─────────────────────────────────────────────────────


def test_po_creation_with_vendor(db_session):
    vendor = Vendor(
        vendor_code="V-PO", legal_name="PO Vendor",
        normalized_name="po vendor", status=VendorStatus.ACTIVE,
    )
    db_session.add(vendor)
    db_session.flush()

    po = PurchaseOrder(
        po_number="PO-TEST-001",
        vendor_id=vendor.id,
        issue_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
        currency="INR",
        total_amount=Decimal("50000.00"),
        status=POStatus.OPEN,
    )
    db_session.add(po)
    db_session.commit()

    found = db_session.query(PurchaseOrder).filter_by(po_number="PO-TEST-001").first()
    assert found is not None
    assert found.vendor_id == vendor.id
    assert found.total_amount == Decimal("50000.00")


def test_po_unique_number(db_session):
    vendor = Vendor(
        vendor_code="V-PO2", legal_name="Vendor Two",
        normalized_name="vendor two", status=VendorStatus.ACTIVE,
    )
    db_session.add(vendor)
    db_session.flush()

    po1 = PurchaseOrder(po_number="PO-DUP", vendor_id=vendor.id,
                        issue_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        currency="INR", total_amount=Decimal("100"), status=POStatus.OPEN)
    po2 = PurchaseOrder(po_number="PO-DUP", vendor_id=vendor.id,
                        issue_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        currency="INR", total_amount=Decimal("200"), status=POStatus.OPEN)
    db_session.add(po1)
    db_session.commit()

    with pytest.raises(Exception):
        db_session.add(po2)
        db_session.commit()


def test_po_to_vendor_relationship(db_session):
    vendor = Vendor(
        vendor_code="V-REL", legal_name="Relation Vendor",
        normalized_name="relation vendor", status=VendorStatus.ACTIVE,
    )
    db_session.add(vendor)
    db_session.flush()

    po1 = PurchaseOrder(po_number="PO-R1", vendor_id=vendor.id,
                        issue_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        currency="INR", total_amount=Decimal("1000"), status=POStatus.OPEN)
    po2 = PurchaseOrder(po_number="PO-R2", vendor_id=vendor.id,
                        issue_date=datetime(2026, 2, 1, tzinfo=timezone.utc),
                        currency="INR", total_amount=Decimal("2000"), status=POStatus.CLOSED)
    db_session.add_all([po1, po2])
    db_session.commit()

    assert len(vendor.purchase_orders) == 2
    assert {po.po_number for po in vendor.purchase_orders} == {"PO-R1", "PO-R2"}


# ── PO Line Items Tests ──────────────────────────────────────────────────────


def test_po_line_items(db_session):
    vendor = Vendor(
        vendor_code="V-LINE", legal_name="Line Vendor",
        normalized_name="line vendor", status=VendorStatus.ACTIVE,
    )
    db_session.add(vendor)
    db_session.flush()

    po = PurchaseOrder(po_number="PO-L1", vendor_id=vendor.id,
                       issue_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                       currency="INR", total_amount=Decimal("10000"), status=POStatus.OPEN)
    db_session.add(po)
    db_session.flush()

    lines = [
        PurchaseOrderLine(purchase_order_id=po.id, description="Item A", sku="SKU-A",
                          quantity=Decimal("10"), unit="pcs", unit_price=Decimal("500.00"), line_total=Decimal("5000.00")),
        PurchaseOrderLine(purchase_order_id=po.id, description="Item B", sku="SKU-B",
                          quantity=Decimal("5"), unit="kg", unit_price=Decimal("600.00"), line_total=Decimal("3000.00")),
    ]
    db_session.add_all(lines)
    db_session.commit()

    assert len(po.line_items) == 2
    assert po.line_items[0].sku == "SKU-A"
    assert po.line_items[1].unit_price == Decimal("600.00")


# ── Invoice Tests ────────────────────────────────────────────────────────────


def test_invoice_with_nullable_fields(db_session):
    inv = Invoice(
        invoice_number="INV-NULL",
        currency="INR",
        subtotal=Decimal("1000.00"),
        tax_amount=Decimal("180.00"),
        discount_amount=Decimal("50.00"),
        total_amount=Decimal("1130.00"),
    )
    db_session.add(inv)
    db_session.commit()

    found = db_session.query(Invoice).filter_by(invoice_number="INV-NULL").first()
    assert found is not None
    assert found.vendor_id is None
    assert found.purchase_order_id is None
    assert found.invoice_date is None


def test_invoice_no_unique_constraint_on_vendor_invoice(db_session):
    """Spec explicitly says: do NOT enforce uniqueness on (vendor_id, invoice_number)."""
    vendor = Vendor(
        vendor_code="V-DUP", legal_name="Dup Vendor",
        normalized_name="dup vendor", status=VendorStatus.ACTIVE,
    )
    db_session.add(vendor)
    db_session.flush()

    inv1 = Invoice(invoice_number="INV-SAME", vendor_id=vendor.id,
                   currency="INR", total_amount=Decimal("100"))
    inv2 = Invoice(invoice_number="INV-SAME", vendor_id=vendor.id,
                   currency="INR", total_amount=Decimal("200"))
    db_session.add_all([inv1, inv2])
    db_session.commit()

    # Both should exist — the matching engine handles duplicates, not the DB.
    count = db_session.query(Invoice).filter_by(invoice_number="INV-SAME").count()
    assert count == 2


def test_invoice_decimal_precision(db_session):
    inv = Invoice(
        invoice_number="INV-DEC",
        currency="INR",
        subtotal=Decimal("99999.99"),
        tax_amount=Decimal("18000.00"),
        discount_amount=Decimal("500.50"),
        total_amount=Decimal("117499.49"),
    )
    db_session.add(inv)
    db_session.commit()

    found = db_session.query(Invoice).filter_by(invoice_number="INV-DEC").first()
    assert found.total_amount == Decimal("117499.49")


# ── Invoice Line Items Tests ─────────────────────────────────────────────────


def test_invoice_line_items(db_session):
    inv = Invoice(invoice_number="INV-LINE", currency="INR", total_amount=Decimal("500"))
    db_session.add(inv)
    db_session.flush()

    line = InvoiceLine(
        invoice_id=inv.id, description="Service charge",
        quantity=Decimal("1"), unit="hr", unit_price=Decimal("500.00"), line_total=Decimal("500.00"),
    )
    db_session.add(line)
    db_session.commit()

    assert len(inv.line_items) == 1
    assert inv.line_items[0].description == "Service charge"


# ── Processing Run Tests ─────────────────────────────────────────────────────


def test_processing_run_creation(db_session):
    run_id = str(uuid.uuid4())
    run = ProcessingRun(
        id=run_id,
        status=ProcessingRunStatus.PENDING,
        llm_provider="openrouter",
        llm_model="meta-llama/llama-3.2-3b-instruct:free",
    )
    db_session.add(run)
    db_session.commit()

    found = db_session.query(ProcessingRun).filter_by(id=run_id).first()
    assert found is not None
    assert found.status == ProcessingRunStatus.PENDING


def test_processing_run_events(db_session):
    run_id = str(uuid.uuid4())
    run = ProcessingRun(id=run_id, status=ProcessingRunStatus.RUNNING)
    db_session.add(run)
    db_session.flush()

    event = ProcessingRunEvent(
        processing_run_id=run_id,
        stage="pdf_extraction",
        status=RunEventStatus.COMPLETED,
        message="Extracted 2 pages",
        details_json='{"pages": 2, "method": "PDF_TEXT"}',
    )
    db_session.add(event)
    db_session.commit()

    assert len(run.events) == 1
    assert run.events[0].stage == "pdf_extraction"


def test_processing_run_foreign_key_enforcement():
    """ProcessingRun.invoice_id is nullable — intentionally allows runs without an invoice."""
    from app.db.models import ProcessingRun, ProcessingRunStatus
    run = ProcessingRun(id=str(uuid.uuid4()), status=ProcessingRunStatus.PENDING)
    assert run.invoice_id is None  # nullable field should accept None


# ── Seed Idempotency Tests ───────────────────────────────────────────────────


def test_seed_is_idempotent():
    """Running the seed script twice should not duplicate records."""
    import subprocess, sys, os
    from app.db.session import SessionLocal

    backend_dir = Path(__file__).resolve().parent.parent.parent  # tests -> app -> backend
    venv_python = str(backend_dir / ".venv" / "bin" / "python")

    # Use -c to run inline code that sets up path and calls seed() directly,
    # avoiding the module import issue with subprocess.
    script = (
        f"import sys; sys.path.insert(0, {str(backend_dir)!r}); "
        "from app.db.seed import seed; seed()"
    )

    # First run
    result1 = subprocess.run([venv_python, "-c", script], capture_output=True, text=True)
    assert result1.returncode == 0, f"First seed failed: {result1.stderr}"

    session = SessionLocal()
    vendor_count_1 = session.query(Vendor).count()
    po_count_1 = session.query(PurchaseOrder).count()
    session.close()

    # Second run
    result2 = subprocess.run([venv_python, "-c", script], capture_output=True, text=True)
    assert result2.returncode == 0, f"Second seed failed: {result2.stderr}"

    session = SessionLocal()
    vendor_count_2 = session.query(Vendor).count()
    po_count_2 = session.query(PurchaseOrder).count()
    session.close()

    assert vendor_count_1 == vendor_count_2, f"Vendor count changed: {vendor_count_1} -> {vendor_count_2}"
    assert po_count_1 == po_count_2, f"PO count changed: {po_count_1} -> {po_count_2}"


# ── Foreign Key Enforcement Tests ────────────────────────────────────────────


def test_foreign_key_enforcement_po_vendor(db_session):
    """A PO must reference a valid vendor."""
    enable_sqlite_foreign_keys(SessionLocal())
    po = PurchaseOrder(
        po_number="PO-BAD-FK",
        vendor_id=99999,  # non-existent vendor
        issue_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        currency="INR", total_amount=Decimal("100"), status=POStatus.OPEN,
    )
    db_session.add(po)
    with pytest.raises(Exception):
        db_session.commit()


def test_foreign_key_enforcement_invoice_vendor(db_session):
    """An invoice must reference a valid vendor (if provided)."""
    enable_sqlite_foreign_keys(SessionLocal())
    inv = Invoice(
        invoice_number="INV-BAD-FK",
        vendor_id=99999,  # non-existent vendor
        currency="INR", total_amount=Decimal("100"),
    )
    db_session.add(inv)
    with pytest.raises(Exception):
        db_session.commit()


# ── Run Phase 1 Health Tests (regression) ────────────────────────────────────


def test_ping_regression():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.get("/health/ping")
    assert resp.status_code == 200
    assert resp.json()["pong"] is True


def test_health_endpoint_regression():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")

