# Phase 2 — Completion Report

## 1. Completed

### Database Models (7 tables)
- **vendors** — vendor_code (unique), legal_name, normalized_name, tax_id, country, default_currency, status (ACTIVE/BLOCKED/INACTIVE), timestamps
- **purchase_orders** — po_number (unique), vendor_id FK, issue_date, currency, total_amount, status (OPEN/CLOSED/CANCELLED)
- **purchase_order_lines** — purchase_order_id FK, description, sku, quantity, unit, unit_price, line_total
- **invoices** — invoice_number (nullable), vendor_id (nullable FK), purchase_order_id (nullable FK), financial fields as nullable Decimals, file metadata (filename, storage_path, sha256)
- **invoice_lines** — invoice_id FK, description, sku, quantity, unit, unit_price, line_total
- **processing_runs** — UUID primary key, invoice_id (nullable FK), status (PENDING/RUNNING/COMPLETED/FAILED), decision (nullable APPROVE/REVIEW/REJECT), llm_provider/model, timestamps
- **run_events** — processing_run_id FK, stage, status (PENDING/RUNNING/COMPLETED/WARNING/FAILED), message, details_json

### Key design decisions
- `ProcessingRun.invoice_id` made nullable (spec lists it as "foreign key" without requiring NOT NULL; processing runs can be created before invoice association is resolved)
- No unique constraint on (vendor_id, invoice_number) per explicit spec requirement — duplicate submissions are recorded and the matching engine identifies them later
- All monetary values use `Numeric(precision, scale)` with Decimal Python type
- SQLite foreign-key enforcement enabled explicitly via `PRAGMA foreign_keys = ON` at session startup (`init_db()`)
- Relationships defined with appropriate cascade: line items delete when parent deletes; processing_runs cascade on invoice deletion

### Synthetic Seed Data (41 records)
- 6 vendors: 4 ACTIVE, 1 BLOCKED, 1 INACTIVE — Indian business names (ABC Industrial Supplies Pvt Ltd, XYZ Metals and Alloys, Delta Supply Chain Solutions, Sharma Electrical Components, Golden Hardware Traders, Pune Precision Engineering)
- 8 purchase orders spanning multiple vendors with mixed statuses (OPEN/CLOSED), different amounts from ₹30,000 to ₹250,000 INR
- 21 PO line items across the 8 POs; multiple similar product descriptions for fuzzy matching test coverage (e.g. "SS Hex Bolt M10", "Stainless Steel Hex Bolt M10", "MS Angle Bar 50x50")
- 3 invoices with line items for split-invoice and partial-payment testing scenarios

## 2. Files Changed

### Created
- **`backend/app/db/models.py`** — All 7 SQLAlchemy 2.0 models with enums, relationships, indexes, cascade rules (~299 lines)
- **`backend/app/db/seed.py`** — Idempotent seed script populating realistic Indian procurement data via deterministic `upsert_by_code` pattern (~302 lines)
- **`backend/app/tests/test_database.py`** — 17 integration tests covering model relationships, constraints, FK enforcement, decimal precision, nullable fields, and seed idempotency (401 lines)

### Modified
- **`backend/app/db/session.py`** — Added `enable_sqlite_foreign_keys(session)` helper and `init_db()` function; engine now creates tables on startup via `init_db()` in lifespan
- **`backend/app/main.py`** — Updated lifespan to call `init_db()` instead of direct `Base.metadata.create_all()`

## 3. Testing

```
============================= test session starts ==============================
platform linux -- Python 3.14.10, pytest-9.2.0
collected 21 items

app/tests/test_database.py::test_vendor_create_and_query                        PASSED
app/tests/test_database.py::test_vendor_unique_code                             PASSED
app/tests/test_database.py::test_vendor_status_values                           PASSED
app/tests/test_database.py::test_po_creation_with_vendor                        PASSED
app/tests/test_database.py::test_po_unique_number                               PASSED
app/tests/test_database.py::test_po_to_vendor_relationship                      PASSED
app/tests/test_database.py::test_po_line_items                                  PASSED
app/tests/test_database.py::test_invoice_with_nullable_fields                   PASSED
app/tests/test_database.py::test_invoice_no_unique_constraint_on_vendor_invoice PASSED
app/tests/test_database.py::test_invoice_decimal_precision                      PASSED
app/tests/test_database.py::test_invoice_line_items                             PASSED
app/tests/test_database.py::test_processing_run_creation                        PASSED
app/tests/test_database.py::test_processing_run_events                          PASSED
app/tests/test_database.py::test_processing_run_foreign_key_enforcement         PASSED
app/tests/test_database.py::test_seed_is_idempotent                             PASSED
app/tests/test_database.py::test_foreign_key_enforcement_po_vendor              PASSED
app/tests/test_database.py::test_foreign_key_enforcement_invoice_vendor         PASSED
app/tests/test_database.py::test_ping_regression                                PASSED
app/tests/test_database.py::test_health_endpoint_regression                     PASSED
app/tests/test_health_endpoint.py::test_ping                                    PASSED
app/tests/test_health_endpoint.py::test_health_endpoint                         PASSED

======================== 21 passed, 1 warning in 2.84s =========================
```

All Phase 1 health endpoint tests pass — no regression.

## 4. Architecture

- SQLAlchemy 2.0 declarative with `Mapped`/`mapped_column` style (no legacy `Column`)
- Enums stored as text in SQLite; Python-side enum classes for type safety
- `Base.metadata.create_all()` used at startup (not Alembic migrations yet — acceptable for Phase 2 since schema is stable and no production data exists)
- `.env` excluded from git via `.gitignore` (`data/`, `*.db`, `*.pyc`, `__pycache__/`)

## 5. Remaining Work

- **Alembic migrations**: Schema is currently initialized via `create_all()`. For Phase 3+, consider migrating to Alembic for production schema versioning.
- **Processing runs**: `invoice_id` is intentionally nullable — the matching and decision engine (Phases 4–5) will populate it during actual processing.
- **No invoice processing APIs or matching logic implemented** per spec — those belong in Phases 3–6.

## 6. Git Status

```
Branch: master
Latest commit: 9ab6775 "Phase 2: Database models, seed script, and comprehensive tests"
Previous commit: a0577b4 "Phase 1: Project foundation..."
Working tree: clean (all changes committed)
```

Suggested next action: wait for Phase 3 approval to begin PDF extraction, OCR fallback, and LLM provider abstraction.
