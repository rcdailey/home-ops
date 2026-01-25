#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${SECRET_DOMAIN:-}" ]]; then
    echo "ERROR: SECRET_DOMAIN env var not set. Add to .mise.local.toml"
    exit 1
fi

output=""
for file in "$@"; do
    if [[ -f "$file" ]]; then
        matches=$(grep -nF "$SECRET_DOMAIN" "$file" 2>/dev/null || true)
        if [[ -n "$matches" ]]; then
            output+="$file:"$'\n'
            while IFS= read -r line; do
                output+="  $line"$'\n'
            done <<< "$matches"
        fi
    fi
done

if [[ -n "$output" ]]; then
    echo "$output"
    echo "ERROR: Real domain detected. Use secret manager or redact."
    exit 1
fi
