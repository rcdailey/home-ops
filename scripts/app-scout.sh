#!/bin/bash
set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Install requirements if needed
pip install --quiet --upgrade pip
pip install --quiet -r "${SCRIPT_DIR}/app-scout/requirements.txt"

# Run the Python script with all arguments passed through
python "${SCRIPT_DIR}/app-scout/app-scout.py" "$@"
