#!/usr/bin/env bash
# Run TaxMind locally: builds the web app if needed, then serves app + API on http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")/.."
pip install -q -r requirements.txt -r server/requirements.txt
if [ ! -f web/dist/index.html ] || [ "${REBUILD:-0}" = "1" ]; then
  (cd web && npm ci && npm run build)
fi
exec python -m uvicorn taxmind_server.main:app --app-dir server --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
