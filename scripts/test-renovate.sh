#!/usr/bin/env bash

# Test script for renovate configuration
# This script runs renovate on the current repository to validate configuration
# changes and see actual PR titles in debug output

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_FILE="$SCRIPT_DIR/renovate.log"

cd "$PROJECT_ROOT"

# Set up environment
export GITHUB_COM_TOKEN="${GITHUB_COM_TOKEN:-$(gh auth token 2>/dev/null || echo '')}"

if [[ -z "$GITHUB_COM_TOKEN" ]]; then
    echo "Error: No GitHub token found. Please run 'gh auth login' first."
    exit 1
fi

echo "Running renovate with debug logging..."

# Run renovate with comprehensive logging on local working copy
# All output goes to log file, nothing to stdout/stderr
LOG_LEVEL=debug renovate \
    --platform=local \
    --dry-run=full \
    --print-config \
    > "$OUTPUT_FILE" 2>&1

echo "Renovate test completed. Debug logs available at: $OUTPUT_FILE"
