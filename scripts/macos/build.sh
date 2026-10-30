#!/usr/bin/env bash
# Build frontend production bundle (apps/web/dist) on macOS
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WEB="$ROOT/apps/web"

cd "$WEB"
if [[ ! -d node_modules ]]; then
  echo "Installing frontend deps..."
  npm install
fi
echo "Building frontend..."
npm run build
echo "Done. Output: apps/web/dist"
