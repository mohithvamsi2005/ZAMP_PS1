# Zamp Invoice Intelligence

AI-powered invoice processing workflow: PDF upload → extraction → matching → deterministic decision (APPROVE / REVIEW / REJECT) with full audit trail.

## Architecture

- **Frontend**: React + Vite + TypeScript
- **Backend**: Python + FastAPI
- **Database**: SQLite
- **PDF extraction**: PyMuPDF (`fitz`) — added in Phase 3
- **OCR fallback**: Tesseract + `pytesseract` — added in Phase 3
- **LLM extraction**: Configurable OpenRouter / `llama.cpp` adapter — added in Phase 3
- **Matching**: RapidFuzz for fuzzy vendor/PO matching
- **Decision engine**: Deterministic Python business rules

## LLM Provider Configuration

The system supports two LLM backends via environment variables. The `llama.cpp` server runs on a **remote machine** (not localhost).

```bash
# Backend .env
LLM_PROVIDER=openrouter          # or llamacpp
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=your_key_here
LLM_MODEL=meta-llama/llama-3.2-3b-instruct:free

# For local llama.cpp (remote server):
# LLM_PROVIDER=llamacpp
# LLM_BASE_URL=http://<LLAMA_SERVER_IP>:PORT/v1
# LLM_API_KEY=your_key_here
# LLM_MODEL=model-alias
```

**Security note**: Never expose the `llama.cpp` server publicly without authentication and network security. Use OpenRouter for deployed demos.

## Project Structure

```
zamp-invoice-intelligence/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI route handlers
│   │   ├── core/         # Config, logging
│   │   ├── db/           # SQLAlchemy models & session
│   │   ├── schemas/      # Pydantic request/response schemas
│   │   ├── services/     # Business logic (Phases 3–6)
│   │   └── tests/        # pytest unit/integration tests
│   ├── data/sample_invoices/
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── api/
│   │   └── types/
│   ├── package.json
│   └── .env.example
└── docs/
```

## Development

### Prerequisites

- Python 3.12+ (use `/usr/bin/python3` — the Hermes venv lacks some packages)
- Node.js 22+ / npm 11+
- Tesseract OCR (system binary) — install before Phase 3: `sudo dnf install tesseract`
- PyMuPDF — added in Phase 3

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # Edit with your API keys
uvicorn app.main:app --reload --port 8000
```

Run tests:
```bash
PYTHONPATH=. pytest app/tests/ -v
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_URL=http://localhost:8000/api
npm run dev            # http://localhost:5173
```

Build for production:
```bash
npm run build
```

### Verify Both Services

```bash
curl http://localhost:8000/health/ping   # {"pong":true}
curl http://localhost:8000/health        # {"status":"ok","database":"connected"}
```

## Implementation Phases

| Phase | Focus | Status |
|---|---|---|
| 0 | Repository audit & architecture validation | ✅ Done |
| 1 | Project foundation (this phase) | ✅ Done |
| 2 | Database models & seed data | ⏳ Pending |
| 3 | PDF extraction + LLM integration | ⏳ Pending |
| 4 | Matching & duplicate detection | ⏳ Pending |
| 5 | Decision engine | ⏳ Pending |
| 6 | Backend workflow orchestration | ⏳ Pending |
| 7 | Frontend dashboard | ⏳ Pending |
| 8 | Integration testing & edge cases | ⏳ Pending |
| 9 | Deployment & demo prep | ⏳ Pending |

## Known Limitations (Phase 1)

- No database tables beyond the SQLite engine — models populated in Phase 2
- No PDF extraction, OCR, or LLM integration yet
- Frontend shows a basic health check page only
- Tesseract and PyMuPDF not yet installed (Phase 3 dependencies)

## Demo Requirements

Per the Zamp case study, the final submission must include:
1. A live, runnable process link
2. A 5-minute demo video showing happy path + edge cases
