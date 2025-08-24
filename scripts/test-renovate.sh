#!/usr/bin/env bash

# Test script for renovate configuration
# This script runs renovate on the current repository to validate configuration
# changes and see actual PR titles in debug output

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_FILE="/tmp/renovate-test-output-$$.log"

cleanup() {
    echo "Log file saved at: $OUTPUT_FILE"
}

trap cleanup EXIT

cd "$PROJECT_ROOT"

echo "Testing renovate configuration on home-ops repository..."
echo "This will show us the actual PR titles that would be generated"

# Set up environment
export GITHUB_COM_TOKEN="${GITHUB_COM_TOKEN:-$(gh auth token 2>/dev/null || echo '')}"

if [[ -z "$GITHUB_COM_TOKEN" ]]; then
    echo "Error: No GitHub token found. Please run 'gh auth login' first."
    exit 1
fi

# Run renovate with comprehensive logging on local working copy
echo "Running renovate with debug logging on local working copy..."
echo "This may take a few minutes..."
LOG_LEVEL=debug renovate \
    --platform=local \
    --dry-run=full \
    --print-config \
    > "$OUTPUT_FILE" 2>&1

echo "Renovate finished. Processing output..."

echo ""
echo "=== ANALYSIS ==="
echo "Looking for group commit message topics and PR titles in the output..."
echo ""

# Extract and display relevant information about groups and PR titles
echo "Searching for group-related configuration:"
grep -i "group\|commitMessageTopic" "$OUTPUT_FILE" | head -20 || echo "No group config matches found"

echo ""
echo "Searching for PR title generation:"
grep -i "pr.*title\|branch.*name\|commit.*message" "$OUTPUT_FILE" | head -20 || echo "No PR title matches found"

echo ""
echo "Searching for package grouping:"
grep -i "cert-manager\|immich\|rook.*ceph" "$OUTPUT_FILE" | head -10 || echo "No package grouping matches found"

echo ""
echo "Full log available at: $OUTPUT_FILE"
