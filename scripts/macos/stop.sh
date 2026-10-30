#!/usr/bin/env bash
# Stop T-Dashboard API (:8000) and Web (:5173) on macOS
set -uo pipefail

kill_port() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "Stopping PIDs on port $port: $pids"
    # shellcheck disable=SC2086
    kill -TERM $pids 2>/dev/null || true
    sleep 1
    # shellcheck disable=SC2086
    kill -KILL $pids 2>/dev/null || true
  fi
}

kill_port 8000
kill_port 5173
sleep 1
echo "Stopped. Ports 8000 / 5173 should be free."
