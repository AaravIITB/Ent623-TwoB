#!/usr/bin/env bash
# Start TwoB on this computer (Mac or Linux):  bash scripts/run.sh
# First run: makes a private Python environment in .venv and installs what TwoB needs (a few minutes).
# Then opens http://localhost:8000 in your browser.
set -euo pipefail
cd "$(dirname "$0")/.."

# 1. A Python 3.10 or newer
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo ""
  echo "TwoB needs Python 3.10 or newer, and this computer doesn't have it."
  echo "Install it from https://www.python.org/downloads/ (macOS installer), then run this again."
  exit 1
fi

# 2. A private environment with TwoB's packages (only the first time)
if [ ! -x .venv/bin/python ]; then
  echo "Setting up TwoB (first run only, takes a few minutes)..."
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements-app.txt
fi

# 3. The web pages (already built in the zip; rebuilt only if missing and Node.js is installed)
if [ ! -f web/dist/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    (cd web && npm ci && npm run build)
  else
    echo "The web pages are missing and Node.js isn't installed. Use the TwoB zip (it includes them), or install Node.js from https://nodejs.org"
    exit 1
  fi
fi

PORT="${PORT:-8000}"
URL="http://localhost:${PORT}"
echo ""
echo "TwoB is starting at ${URL}  (first login: admin / admin123). Press Ctrl+C here to stop it."
( sleep 3; (command -v open >/dev/null && open "$URL") || (command -v xdg-open >/dev/null && xdg-open "$URL") || true ) >/dev/null 2>&1 &
exec .venv/bin/python -m uvicorn taxmind_server.main:app --app-dir server --host "${HOST:-127.0.0.1}" --port "$PORT" --no-access-log
