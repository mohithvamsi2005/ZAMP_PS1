"""Phase 6 — persistence of processing results.

Adds `processing_runs.document_meta_json`: persisted document-processing
metadata (page-level extraction methods, OCR info, document hash and warnings)
so a completed run can be fully reconstructed without re-reading the PDF.

Non-destructive: single nullable column addition. Existing databases keep all
data (no table rebuild required for ADD COLUMN on SQLite).

Revision ID: 0002_phase6_document_meta
Revises: 0001_baseline_schema
Create Date: 2026-11-09
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0002_phase6_document_meta"
down_revision = "0001_baseline_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "processing_runs",
        sa.Column("document_meta_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    # SQLite batch mode allows the column drop via table rebuild.
    with op.batch_alter_table("processing_runs") as batch:
        batch.drop_column("processing_runs", "document_meta_json")
