#!/usr/bin/env bash
# Restart T-Dashboard API (:8000) and Web (:5173) on macOS
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$SCRIPT_DIR/stop.sh"
sleep 1

PY="$ROOT/apps/server/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Missing server venv. Run scripts/macos/dev.sh first." >&2
  exit 1
fi

mkdir -p "$ROOT/.run"
echo "Starting API on :8000 ..."
(
  cd "$ROOT/apps/server"
  nohup "$PY" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 \
    >"$ROOT/.run/api.log" 2>&1 &
  echo $! >"$ROOT/.run/api.pid"
)

echo "Starting Web on :5173 ..."
(
  cd "$ROOT/apps/web"
  nohup npm run dev >"$ROOT/.run/web.log" 2>&1 &
  echo $! >"$ROOT/.run/web.pid"
)

sleep 2
echo "Restarted. Open http://localhost:5173"
echo "API health: http://127.0.0.1:8000/api/health"
echo "Logs: $ROOT/.run/api.log , $ROOT/.run/web.log"
