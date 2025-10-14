#!/usr/bin/env bash
set -euo pipefail

# Pre-commit hook for Vector VRL validation
# Validates VRL configurations in HelmRelease files and standalone .vrl files

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VALIDATOR="${PROJECT_ROOT}/scripts/test-vector-config.py"

exit_code=0

# Process each file passed by pre-commit
for file in "$@"; do
    # Skip if file doesn't exist (deleted files)
    if [[ ! -f "$file" ]]; then
        continue
    fi

    # Check if file contains VRL configuration
    # Look for: source: | followed by VRL code in HelmReleases
    # Or .vrl files directly
    if [[ "$file" == *.vrl ]] || grep -q "source: |" "$file" 2>/dev/null; then
        echo "Validating VRL in: $file"
        if ! "$VALIDATOR" "$file"; then
            exit_code=1
        fi
    fi
done

exit $exit_code
