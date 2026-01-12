#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOMEPAGE_DIR="$SCRIPT_DIR/../kubernetes/apps/default/homepage"

cd "$HOMEPAGE_DIR"

cleanup() {
    echo ""
    echo "Stopping preview..."
    docker compose down -v --remove-orphans 2>/dev/null
    exit 0
}

trap cleanup INT TERM

echo "Starting Homepage preview..."
echo ""
echo "  Open: http://localhost:3080"
echo ""
echo "Edit config/*.yaml files and refresh browser to see changes."
echo "Press Ctrl+C to stop."
echo ""

docker compose up --force-recreate --remove-orphans
