#!/usr/bin/env bash
# Install project-local Allure CLI into tools/allure (requires Node + Java 8+)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIR="$ROOT/tools/allure"

echo "Checking Java..."
java -version

cd "$DIR"
npm install

CLI="$DIR/node_modules/allure-commandline/dist/bin/allure"
if [[ ! -x "$CLI" ]]; then
  echo "Install finished but allure not found at $CLI" >&2
  exit 1
fi

echo "Allure installed: $CLI"
"$CLI" --version
echo "Restart the API if it was already running, then click Allure report again."
