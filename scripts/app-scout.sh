#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/app-scout/.venv"
REQ_FILE="${SCRIPT_DIR}/app-scout/requirements.txt"
STAMP_FILE="${VENV_DIR}/.requirements-stamp"

# Recreate venv if missing or if its Python interpreter is broken (e.g. mise upgrade)
needs_rebuild=false
if [[ ! -d "$VENV_DIR" ]]; then
    needs_rebuild=true
elif ! "$VENV_DIR/bin/python3" --version &>/dev/null; then
    echo "Stale venv detected (Python interpreter missing), rebuilding..." >&2
    rm -rf "$VENV_DIR"
    needs_rebuild=true
fi

if [[ "$needs_rebuild" == true ]]; then
    echo "Creating Python virtual environment..." >&2
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# Reinstall deps only when requirements.txt changes
if [[ ! -f "$STAMP_FILE" ]] || ! diff -q "$REQ_FILE" "$STAMP_FILE" &>/dev/null; then
    pip install --quiet --upgrade pip
    pip install --quiet -r "$REQ_FILE"
    cp "$REQ_FILE" "$STAMP_FILE"
fi

python "${SCRIPT_DIR}/app-scout/app-scout.py" "$@"
