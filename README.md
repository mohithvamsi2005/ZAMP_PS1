# Zamp Invoice Intelligence

Autonomous invoice processing with deterministic validation — PDF upload → extraction → matching → decision with a complete audit trail. React + Vite + TypeScript frontend, Python + FastAPI backend, SQLite persistence.

```text
 Invoice PDF ─┬─► Extraction (PyMuPDF + OCR fallback) ─► LLM (OpenRouter / llama.cpp)
              │
              ├─► Vendor match / PO match / Duplicate check
              │
              ├─► Amount · tax · line-item validation (Decimal-safe)
              │
              └─► Deterministic decision engine → APPROVE | REVIEW | REJECT
```

- **Decisions are deterministic**, not LLM-generated. The LLM extracts; Python decides.
- **Audit trail** — every decision records `policy_version`, the full rule trace and the evidence snippet that drove it.
- **Fail-safe** — any failed check or low confidence → REVIEW, never silent APPROVE.

See `DEPLOYMENT.md`, `DEMO_GUIDE.md`, and the phase reports for the rest.

## Quick start (local dev)

```bash
cd backend
.venv/bin/pip install -r requirements.txt
cd ../frontend && npm ci && npm run build
cd ../backend && ./scripts/reset_demo_db.sh --reset
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# → http://127.0.0.1:8000
```

Without an `AUTH_PASSWORD` in `backend/.env`, auth is disabled for local convenience. In any shared environment, set `AUTH_PASSWORD`/`AUTH_SECRET` (see `DEPLOYMENT.md` or the full `backend/.env.example`).

## Stack

| Layer | Choice | Notes |
|---|---|---|
| UI | React 19 + Vite 6 + TS | Custom design system; 50 vitest tests |
| API | FastAPI 0.162 + Pydantic 2 | 279 pytest tests |
| DB | SQLite (default) / Postgres-ready | Alembic-migrated (`0001` baseline + `0002_phase6_document_meta`) |
| OCR | Tesseract 5 + PyMuPDF | Text-layer first, OCR fallback |
| LLM | OpenAI-compatible (OpenRouter / llama.cpp) | Compact prompt for tiny local models, rich evidence-annotated prompt for capable ones |
| Auth | Single-operator token (HttpOnly cookie, HMAC-SHA256) | Enabled only when `AUTH_PASSWORD` is set |

## Repo layout

```
zamp-invoice-intelligence/
├── backend/          # FastAPI app: api/ services/ schemas/ db/ core/ tests/
├── frontend/         # React app: src/pages api types components utils hooks
├── docs/             # additional design/review docs
├── README.md
├── DEPLOYMENT.md     # production runbook
├── DEMO_GUIDE.md     # five-minute scripted walkthrough
└── SECURITY_POSTURE.md
```

## Testing

```bash
cd backend  && .venv/bin/python -m pytest app/tests -q   # 279 green
cd frontend && npx vitest run                             # 50 green
cd frontend && npm run build                              # dist/
```
