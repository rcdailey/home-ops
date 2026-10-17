#!/usr/bin/env bash
# topf secretsProvider contract: https://postfinance.github.io/topf/main/providers/
# The bundle lives in Infisical (/bootstrap) as TALOS_SECRETS_BUNDLE and is injected into the
# environment by `just talos topf`. `put` is refused: topf only calls it after `get` returns
# nothing, and silently generating new cluster PKI must never replace the live bundle.
set -euo pipefail

case "${1:-} ${2:-}" in
    "secrets get")
        if [[ -z "${TALOS_SECRETS_BUNDLE:-}" ]]; then
            echo "TALOS_SECRETS_BUNDLE is not set; run topf through 'just talos topf'" >&2
            exit 1
        fi
        printf '%s\n' "$TALOS_SECRETS_BUNDLE"
        ;;
    "secrets put")
        echo "Refusing to store a generated secrets bundle; add it to Infisical manually" >&2
        exit 1
        ;;
    *)
        echo "usage: $0 secrets get|put <cluster>" >&2
        exit 2
        ;;
esac
