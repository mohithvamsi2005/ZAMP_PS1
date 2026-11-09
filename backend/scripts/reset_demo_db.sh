#!/usr/bin/env bash
# Reset and reseed the dedicated demo database (data/demo.db).
#
# DESTRUCTIVE only when --reset is passed. Without it, the script is a no-op
# unless the demo DB does not exist yet. Never touches data/app.db.
set -euo pipefail

cd "$(dirname "$0")/.."

DEMO_DB="${DEMO_DB:-data/demo.db}"
RESET="${1:-}"

if [[ "$RESET" == "--reset" ]]; then
  echo "Removing $DEMO_DB (demo-only DB)…"
  rm -f "$DEMO_DB"
fi

if [[ -e "$DEMO_DB" ]]; then
  echo "$DEMO_DB already exists — leaving untouched (use --reset to rebuild)."
  exit 0
fi

echo "Creating $DEMO_DB…"
export DATABASE_URL="sqlite:///$(pwd)/$DEMO_DB"
.venv/bin/python - <<'PY'
from app.db.session import init_db  # noqa: F401
from app.db import models  # noqa: F401
from alembic.config import Config
from alembic import command
init_db()
cfg = Config("alembic.ini")
command.stamp(cfg, "0002_phase6_document_meta")
print("schema created + stamped at 0002_phase6_document_meta")
PY

echo "Seeding demo data (vendors, POs, sample invoices)…"
.venv/bin/python -m app.db.seed

echo
echo "Demo DB ready at: $DEMO_DB"
echo "Verify with:"
echo "  DATABASE_URL=sqlite:///\$(pwd)/$DEMO_DB .venv/bin/python -c 'from app.db.session import SessionLocal; from app.db.models import Vendor, PurchaseOrder, Invoice; db = SessionLocal(); print({\"vendors\": db.query(Vendor).count(), \"pos\": db.query(PurchaseOrder).count(), \"invoices\": db.query(Invoice).count()})'"
