#!/bin/bash
set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Create virtual environment if it doesn't exist
VENV_DIR="${SCRIPT_DIR}/app-scout/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Install requirements if needed
pip install --quiet --upgrade pip
pip install --quiet -r "${SCRIPT_DIR}/app-scout/requirements.txt"

# Run the Python script with all arguments passed through
python "${SCRIPT_DIR}/app-scout/app-scout.py" "$@"
