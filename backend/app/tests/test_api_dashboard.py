"""Phase 7 backend additions — dashboard summary, invoice list, document endpoint.

Uses direct DB seeding (not the full workflow) so fixtures are fast and precise.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.db.models import (
    Invoice, ProcessingRun, PurchaseOrder, Vendor, VendorStatus, POStatus,
)
from app.db.session import SessionLocal

FIXTURE_INVOICES = [
    ("INV-TU-1", "APPROVE", None, 10),
    ("INV-TU-2", "REVIEW", None, 20),
    ("INV-TU-3", "REJECT", None, 30),
    ("INV-TU-4", None, "FAILED", None),
    ("INV-TU-5", "APPROVE", None, 40),
    ("INV-TU-6", None, "PENDING", None),
]


def _seed_fixture():
    session = SessionLocal()
    try:
        v = Vendor(
            vendor_code="V-TU-001",
            legal_name="TestCo Fixtures Ltd",
            normalized_name="testco fixtures ltd",
            country="IN",
            default_currency="INR",
            status=VendorStatus.ACTIVE,
        )
        session.add(v)
        session.flush()
        po = PurchaseOrder(
            po_number="PO-TU-1",
            vendor_id=v.id,
            issue_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
            currency="INR",
            total_amount=Decimal("900000.00"),
            status=POStatus.OPEN,
        )
        session.add(po)
        session.flush()

        now = datetime.now(timezone.utc)
        for invoice_number, decision, status, duration in FIXTURE_INVOICES:
            inv = Invoice(
                invoice_number=invoice_number,
                vendor_id=v.id,
                purchase_order_id=po.id,
                currency="INR",
                total_amount=Decimal("10000.00"),
                invoice_date=now,
            )
            session.add(inv)
            session.flush()
            if status == "PENDING":
                run = ProcessingRun(
                    id=str(uuid.uuid4()),
                    invoice_id=inv.id,
                    status="PENDING",
                    decision=None,
                )
            elif status == "FAILED":
                run = ProcessingRun(
                    id=str(uuid.uuid4()),
                    invoice_id=inv.id,
                    status="FAILED",
                    decision=None,
                    started_at=now - timedelta(seconds=5),
                    error_message="simulated extraction failure",
                )
            else:
                run = ProcessingRun(
                    id=str(uuid.uuid4()),
                    invoice_id=inv.id,
                    status="COMPLETED",
                    decision=decision,
                    started_at=now - timedelta(seconds=duration),
                    completed_at=now,
                )
            session.add(run)
        session.commit()
        return {"vendor_id": v.id, "po_id": po.id}
    finally:
        session.close()


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def seeded(client):
    return _seed_fixture()


class TestDashboardSummary:
    def test_summary_counts_from_real_records(self, seeded, client):
        resp = client.get("/api/dashboard/summary")
        assert resp.status_code == 200
        body = resp.json()

        totals = body["totals"]
        assert totals["invoices"] == 6
        assert totals["runs"] == 6
        assert totals["completed_runs"] == 4
        assert totals["failed_runs"] == 1
        assert totals["pending_runs"] == 1
        assert totals["running_runs"] == 0

        assert body["decisions"] == {"APPROVE": 2, "REVIEW": 1, "REJECT": 1}
        assert body["decision_total"] == 4
        assert body["approval_rate"] == 50.0
        assert body["review_queue"] == 1  # one REVIEW case waiting

        durations = [d for _, _, _, d in FIXTURE_INVOICES if d]
        expected_avg = sum(durations) / len(durations)
        assert body["avg_processing_seconds"] == pytest.approx(expected_avg, abs=1.0)

        activity = body["activity_last_14_days"]
        assert len(activity) == 14
        assert activity[-1]["submitted"] == 6  # all seeded today
        assert all("-" in d["date"] for d in activity)

        recent = body["recent_runs"]
        assert len(recent) == 6
        numbers = {r["invoice_number"] for r in recent}
        assert numbers == {inv for inv, _, _, _ in FIXTURE_INVOICES}
        sample = recent[0]
        assert sample["vendor_name"] == "TestCo Fixtures Ltd"
        assert sample["po_reference"] == "PO-TU-1"
        assert sample["status"] in {"COMPLETED", "FAILED", "PENDING"}
        # duration_seconds present on completed rows, None otherwise
        completed = next(r for r in recent if r["status"] == "COMPLETED")
        assert completed["duration_seconds"] is not None

        failed = body["latest_failed_runs"]
        assert len(failed) == 1
        assert failed[0]["status"] == "FAILED"
        assert "simulated extraction failure" in (failed[0]["error_message"] or "")

    def test_summary_empty_when_no_records(self, client):
        resp = client.get("/api/dashboard/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["totals"]["invoices"] == 0
        assert body["decisions"] == {"APPROVE": 0, "REVIEW": 0, "REJECT": 0}
        assert body["approval_rate"] is None
        assert len(body["activity_last_14_days"]) == 14
        assert body["recent_runs"] == []


class TestInvoiceList:
    def test_list_pagination_and_totals(self, seeded, client):
        resp = client.get("/api/invoices")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 6
        assert len(body["invoices"]) == 6

        resp = client.get("/api/invoices", params={"page": 2, "page_size": 2})
        body = resp.json()
        assert body["page"] == 2 and body["page_size"] == 2
        assert len(body["invoices"]) == 2 and body["total"] == 6

    def test_search_and_filters(self, seeded, client):
        resp = client.get("/api/invoices", params={"search": "TU-2"})
        assert [i["invoice_number"] for i in resp.json()["invoices"]] == ["INV-TU-2"]

        resp = client.get("/api/invoices", params={"decision": "REVIEW"})
        assert [i["invoice_number"] for i in resp.json()["invoices"]] == ["INV-TU-2"]
        assert resp.json()["total"] == 1

        resp = client.get("/api/invoices", params={"decision": "APPROVE"})
        assert {i["invoice_number"] for i in resp.json()["invoices"]} == {"INV-TU-1", "INV-TU-5"}

        resp = client.get("/api/invoices", params={"status": "FAILED"})
        assert [i["invoice_number"] for i in resp.json()["invoices"]] == ["INV-TU-4"]

        resp = client.get("/api/invoices", params={"status": "PENDING"})
        assert [i["invoice_number"] for i in resp.json()["invoices"]] == ["INV-TU-6"]

        resp = client.get("/api/invoices", params={"search": "nothing-like-this"})
        assert resp.json()["total"] == 0

    def test_invalid_filters_return_422(self, seeded, client):
        assert client.get("/api/invoices", params={"decision": "BOGUS"}).status_code == 422
        assert client.get("/api/invoices", params={"status": "BOGUS"}).status_code == 422

    def test_sorting(self, seeded, client):
        resp = client.get("/api/invoices", params={"sort_by": "total_amount", "sort_dir": "asc"})
        totals = [float(i["total_amount"]) for i in resp.json()["invoices"]]
        assert totals == sorted(totals)
        resp = client.get("/api/invoices", params={"sort_by": "total_amount", "sort_dir": "desc"})
        totals = [float(i["total_amount"]) for i in resp.json()["invoices"]]
        assert totals == sorted(totals, reverse=True)


class TestInvoiceDocument:
    def test_serves_stored_pdf_bytes(self, client, tmp_path):
        from app.services.workflow import create_invoice_and_run
        payload = b"%PDF-1.4\nPhase 7 document serving test\n" + b"x" * 64
        invoice_id, _run_id = create_invoice_and_run(payload, "weird name <>&.pdf")

        resp = client.get(f"/api/invoices/{invoice_id}/document")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content == payload
        assert f'invoice_{invoice_id}.pdf' in resp.headers["content-disposition"]

        assert client.get("/api/invoices/999999/document").status_code == 404

    def test_document_missing_on_disk_returns_404(self, client, tmp_path):
        from app.services.workflow import create_invoice_and_run
        payload = b"%PDF-1.4\nmissing-test" + b"y" * 32
        invoice_id, _ = create_invoice_and_run(payload, "gone.pdf")
        # Cheat: point the invoice at a path that does not exist
        session = SessionLocal()
        try:
            inv = session.get(Invoice, invoice_id)
            inv.storage_path = "/tmp/definitely-not-here-phase7.pdf"
            session.commit()
        finally:
            session.close()
        assert client.get(f"/api/invoices/{invoice_id}/document").status_code == 404


class TestDashboardReset:
    def test_reset_restores_baseline_and_deletes_only_scoped_uploads(self, seeded, client, tmp_path):
        from pathlib import Path
        from app.core.config import get_settings
        from app.services.workflow import create_invoice_and_run

        payload = b"%PDF-1.4\nreset-test-payload" + b"a" * 32
        uploaded_id, _ = create_invoice_and_run(payload, "reset_me.pdf")

        # Mark the auto-created PENDING run as COMPLETED so reset is permitted
        session = SessionLocal()
        try:
            inv = session.get(Invoice, uploaded_id)
            uploaded_path = Path(inv.storage_path)
            for r in session.query(ProcessingRun).all():
                r.status = "COMPLETED"
                r.decision = "APPROVE"
            # Add an invoice whose storage_path points outside UPLOAD_DIR
            outside_file = tmp_path / "do_not_delete.pdf"
            outside_file.write_bytes(b"%PDF-1.4\nkeep-me")
            decoy = Invoice(
                invoice_number="INV-OUTSIDE",
                storage_path=str(outside_file),
                currency="INR",
                total_amount=Decimal("100.00"),
            )
            session.add(decoy)
            session.commit()
        finally:
            session.close()

        assert uploaded_path.is_file()
        assert Path(get_settings().upload_dir).resolve() in uploaded_path.resolve().parents
        assert outside_file.is_file()

        resp = client.post("/api/dashboard/reset")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["invoices"] == 3
        assert body["runs"] == 0
        assert body["vendors"] == 6
        assert body["purchase_orders"] == 8
        assert body["deleted_files"] == 1

        assert not uploaded_path.exists()
        assert outside_file.is_file()

        summary = client.get("/api/dashboard/summary").json()
        assert summary["totals"]["invoices"] == 3
        assert summary["totals"]["runs"] == 0
        assert summary["decisions"] == {"APPROVE": 0, "REVIEW": 0, "REJECT": 0}

    def test_reset_rejects_when_run_is_in_flight(self, client):
        from app.services.workflow import create_invoice_and_run

        payload = b"%PDF-1.4\nin-flight" + b"z" * 32
        create_invoice_and_run(payload, "inflight.pdf")  # creates a PENDING run

        resp = client.post("/api/dashboard/reset")
        assert resp.status_code == 409
        assert "in progress" in resp.json()["detail"].lower()

        session = SessionLocal()
        try:
            run = session.query(ProcessingRun).first()
            run.status = "RUNNING"
            session.commit()
        finally:
            session.close()

        resp_running = client.post("/api/dashboard/reset")
        assert resp_running.status_code == 409

    def test_reset_respects_auth_and_write_token(self, client):
        from app.core.config import get_settings

        settings = get_settings()
        orig_pw = settings.auth_password
        orig_tok = settings.write_token
        try:
            settings.auth_password = "reset-secret-pw"
            assert client.post("/api/dashboard/reset").status_code == 401

            login = client.post("/api/auth/login", json={"password": "reset-secret-pw"})
            assert login.status_code == 200

            settings.write_token = "write-tok-123"
            assert client.post("/api/dashboard/reset").status_code == 403
            ok = client.post("/api/dashboard/reset", headers={"X-Zamp-Token": "write-tok-123"})
            assert ok.status_code == 200
        finally:
            settings.auth_password = orig_pw
            settings.write_token = orig_tok
