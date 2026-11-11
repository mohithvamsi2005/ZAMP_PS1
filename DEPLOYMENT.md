# Zamp Invoice Intelligence — Deployment Guide

Deployment topology: **one process** serves both the API and the built SPA. Behind token auth. SQLite for persistence.

```
Browser → http://127.0.0.1:8000  (React SPA + FastAPI in one process)
              │
              ├─ Auth: single operator token (HttpOnly cookie, HMAC-signed, 12 h TTL)
              ├─ /api/*            (session/bearer required — 401 otherwise)
              ├─ /health           (public — used by monitors)
              ├─ /api/auth/{status,login,logout}  (public)
              └─ /{full_path:path} (SPA + branded 404)
              │
              └─ SQLite   → data/demo.db           (session persistence)
                 Upload dir → data/uploads        (uploaded PDFs)
                 OCR / PyMuPDF  → in-process
                 LLM          → llamacpp → Ollama at 127.0.0.1:11434 (default)
                                or OpenRouter (set their key in .env)
```

## Requirements

- Linux host with Python ≥ 3.12 and Node ≥ 18
- Tesseract 5
- LLM provider: either `llamacpp` (Ollama or a llama.cpp server) reachable over HTTP, or an OpenRouter account

## Configuration

All configuration flows through `backend/.env` (untracked — never commit it). A complete template lives at `backend/.env.example`.

```bash
cd backend
# ── Cookies/secrets ─ generate fresh randoms ──────────────────────────
python -c "import secrets; print('AUTH_PASSWORD=' + secrets.token_urlsafe(24)); print('AUTH_SECRET='   + secrets.token_hex(32))"
```

Minimum demo settings:

```ini
# ── Persistence
DATABASE_URL=sqlite:///./data/demo.db
UPLOAD_DIR=./data/uploads
MAX_UPLOAD_MB=20

# ── Environment guard
ENVIRONMENT=production

# ── LLM provider (pick one) ───────────────────────────────────────────
LLM_PROVIDER=llamacpp
LLM_BASE_URL=http://LLAMA_SERVER_IP:11434
LLM_API_KEY=local-none
LLM_MODEL=qwen2.5:1.5b
# Or OpenRouter:
# LLM_PROVIDER=openrouter
# LLM_BASE_URL=https://openrouter.ai/api/v1
# LLM_API_KEY=<your key>
# LLM_MODEL=<a free or paid model, e.g. google/gemma-2-9b-it:free>

# ── Access control (REQUIRED in any shared environment) ───────────────
AUTH_PASSWORD=<random>
AUTH_SECRET=<random-hex>
AUTH_SECURE_COOKIE=false         # set true only behind HTTPS

# ── Network/limits
ENVIRONMENT=production
```

`AUTH_*` must be set before you expose the service to anyone. Without an `AUTH_PASSWORD`, auth is **disabled by design** so local dev works out of the box — this is the documented trade-off behind the `localhost` demo.

## First-time setup

```bash
cd backend
.venv/bin/pip install -r requirements.txt
cd ../frontend && npm ci && npm run build
cd ../backend
./scripts/reset_demo_db.sh --reset    # builds data/demo.db, stamps Alembic, seeds vendors + POs
```

## Running

```bash
cd backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. Sign in with `AUTH_PASSWORD`. The frontend calls the backend API on the same origin.

## Restart behaviour

Uvicorn restarts do not lose data. History survives. Uploads and the database live in `data/`.

## Resetting the demo data

```bash
cd backend
./scripts/reset_demo_db.sh --reset     # drops and reseeds data/demo.db — NEVER touches data/app.db
```

## Recommended demo LLM

Because OpenRouter free-tier quotas can be exhausted for the day, the demo is pinned to the **local** `llamacpp` provider (qwen2.5:1.5b on Ollama, 127.0.0.1:11434). The live test in `PHASE_9_REPORT.md` shows exactly what this small model produces — deterministic matching and the decision engine still fire, outcome is **REVIEW** because the tiny model can't emit per-field confidences. Point the deployment at OpenRouter for the full APPROVE outcome when quota permits.

## What is NOT here

- Kubernetes/Helm/ECS — single process by design
- TLS termination — use your own reverse proxy for internet exposure
- Multi-tenant auth — see `SECURITY_POSTURE.md`

## GitHub Codespaces & Cloud Docker Deployment

1. **GitHub Codespaces (`.devcontainer/devcontainer.json`)**:
   - Add `LLM_API_KEY` (and optional `AUTH_PASSWORD`) in GitHub **Settings → Secrets and variables → Codespaces**.
   - Click **Code → Codespaces → Create codespace**. Port `8000` launches automatically; switch its **Ports** visibility to **Public** when sharing live.
2. **Docker / Render (`render.yaml`) / Railway (`railway.toml`)**:
   - Connect the GitHub repository, set `LLM_API_KEY` (OpenRouter key) and `AUTH_PASSWORD` in host environment variables, and deploy with `LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free` and `AUTO_SEED_ON_EMPTY=true`.
