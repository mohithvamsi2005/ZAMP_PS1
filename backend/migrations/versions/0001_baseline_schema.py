"""Baseline schema — Phase 5 state (vendors, POs, invoices, runs, events).

Represents the authoritative schema as of Phase 5 completion, including the
structured JSON audit columns on processing_runs. DDL mirrors
`Base.metadata.create_all()` output; fresh databases may either use
`alembic upgrade head` or `init_db()` + `alembic stamp 0001_baseline_schema`.

Revision ID: 0001_baseline_schema
Revises:
Create Date: 2026-11-09
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001_baseline_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vendor_code", sa.String(50), nullable=False, unique=True),
        sa.Column("legal_name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False, index=True),
        sa.Column("tax_id", sa.String(50), nullable=True),
        sa.Column("country", sa.String(2), nullable=True),
        sa.Column("default_currency", sa.String(3), nullable=True),
        sa.Column("status", sa.Enum("ACTIVE", "BLOCKED", "INACTIVE", name="vendorstatus"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("po_number", sa.String(50), nullable=False, unique=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"), nullable=False),
        sa.Column("issue_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("total_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("status", sa.Enum("OPEN", "CLOSED", "CANCELLED", name="postatus"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_po_vendor_id", "purchase_orders", ["vendor_id"])
    op.create_index("ix_po_number", "purchase_orders", ["po_number"])
    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_order_id", sa.Integer(),
                  sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sku", sa.String(100), nullable=True),
        sa.Column("quantity", sa.Numeric(12, 4), nullable=False),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("unit_price", sa.Numeric(15, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(15, 2), nullable=False),
    )
    op.create_index("ix_po_line_po_id", "purchase_order_lines", ["purchase_order_id"])
    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_number", sa.String(100), nullable=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"), nullable=True),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"), nullable=True),
        sa.Column("invoice_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("subtotal", sa.Numeric(15, 2), nullable=True),
        sa.Column("tax_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("discount_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("total_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("storage_path", sa.String(500), nullable=True),
        sa.Column("file_sha256", sa.String(64), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_invoice_vendor_id", "invoices", ["vendor_id"])
    op.create_index("ix_invoice_file_sha256", "invoices", ["file_sha256"])
    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sku", sa.String(100), nullable=True),
        sa.Column("quantity", sa.Numeric(12, 4), nullable=False),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("unit_price", sa.Numeric(15, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(15, 2), nullable=False),
    )
    op.create_index("ix_inv_line_invoice_id", "invoice_lines", ["invoice_id"])
    op.create_table(
        "processing_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id"), nullable=True),
        sa.Column("status", sa.Enum("PENDING", "RUNNING", "COMPLETED", "FAILED", name="processingrunstatus"), nullable=False),
        sa.Column("decision", sa.Enum("APPROVE", "REVIEW", "REJECT", name="decision"), nullable=True),
        sa.Column("llm_provider", sa.String(50), nullable=True),
        sa.Column("llm_model", sa.String(100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("extraction_json", sa.Text(), nullable=True),
        sa.Column("vendor_match_json", sa.Text(), nullable=True),
        sa.Column("po_match_json", sa.Text(), nullable=True),
        sa.Column("duplicate_check_json", sa.Text(), nullable=True),
        sa.Column("amount_validation_json", sa.Text(), nullable=True),
        sa.Column("line_item_validation_json", sa.Text(), nullable=True),
        sa.Column("tax_validation_json", sa.Text(), nullable=True),
        sa.Column("decision_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_run_invoice_id", "processing_runs", ["invoice_id"])
    op.create_index("ix_run_status", "processing_runs", ["status"])
    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("processing_run_id", sa.String(36),
                  sa.ForeignKey("processing_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("status", sa.Enum("PENDING", "RUNNING", "COMPLETED", "WARNING", "FAILED", name="runeventstatus"), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_event_run_id", "run_events", ["processing_run_id"])


def downgrade() -> None:
    op.drop_table("run_events")
    op.drop_table("processing_runs")
    op.drop_table("invoice_lines")
    op.drop_table("invoices")
    op.drop_table("purchase_order_lines")
    op.drop_table("purchase_orders")
    op.drop_table("vendors")
