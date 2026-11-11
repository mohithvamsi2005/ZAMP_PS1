#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

sudo apt-get update
sudo apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng fonts-dejavu-core
sudo rm -rf /var/lib/apt/lists/*

cd "$ROOT_DIR/backend"
python3 -m venv .venv
.venv/bin/pip install --no-cache-dir -r requirements.txt

cd "$ROOT_DIR/frontend"
npm ci
npm run build

cd "$ROOT_DIR/backend"
mkdir -p data/uploads data/synthetic_invoices
chmod +x scripts/reset_demo_db.sh
bash scripts/reset_demo_db.sh
.venv/bin/python scripts/generate_synthetic_data.py
