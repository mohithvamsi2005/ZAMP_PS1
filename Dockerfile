# Stage 1: Build the React + Vite frontend bundle
FROM node:20-slim AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Unified FastAPI + SPA + Tesseract OCR runtime
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production \
    DATABASE_URL=sqlite:///./data/demo.db \
    UPLOAD_DIR=./data/uploads \
    MAX_UPLOAD_MB=20 \
    AUTO_SEED_ON_EMPTY=true \
    ALLOW_PUBLIC_WRITE=true \
    LLM_PROVIDER=openrouter \
    LLM_BASE_URL=https://openrouter.ai/api/v1 \
    LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free \
    LLM_TIMEOUT_SECONDS=120 \
    LLM_MAX_RETRIES=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend-builder /build/frontend/dist /app/frontend/dist

RUN mkdir -p data/uploads data/synthetic_invoices && chmod +x scripts/reset_demo_db.sh || true

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health')"

CMD ["sh", "-c", "mkdir -p data/uploads && python scripts/generate_synthetic_data.py >/dev/null 2>&1 || true; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
