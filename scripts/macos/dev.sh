#!/usr/bin/env bash
# Start T-Dashboard (macOS): API :8000 + Web :5173
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Prefer python3; Homebrew python is common on macOS
PYTHON_BIN="${PYTHON_BIN:-python3}"

PY="$ROOT/apps/server/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Creating venv..."
  "$PYTHON_BIN" -m venv "$ROOT/apps/server/.venv"
  "$PY" -m pip install -r "$ROOT/apps/server/requirements.txt"
  "$PY" -m playwright install chromium
fi

if [[ ! -d "$ROOT/apps/web/node_modules" ]]; then
  echo "Installing frontend deps..."
  (cd "$ROOT/apps/web" && npm install)
fi

cleanup() {
  [[ -n "${API_PID:-}" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "${WEB_PID:-}" ]] && kill "$WEB_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting API on :8000 and Web on :5173 ..."
(
  cd "$ROOT/apps/server"
  exec "$PY" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
) &
API_PID=$!

(
  cd "$ROOT/apps/web"
  exec npm run dev
) &
WEB_PID=$!

echo "API PID=$API_PID  WEB PID=$WEB_PID"
echo "Open http://localhost:5173"
echo "Press Ctrl+C to stop."
wait "$API_PID"
