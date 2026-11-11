#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR/backend"

# Stop any stale server on restart before launching fresh background uvicorn
pkill -f "uvicorn app.main:app" >/dev/null 2>&1 || true

nohup .venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips='*' \
  > /tmp/zamp-server.log 2>&1 &

echo "Zamp server started on port 8000 (logs: /tmp/zamp-server.log)"
