#!/usr/bin/env bash

# kopia.sh - Convenience wrapper for kopia commands via kopia pod

set -euo pipefail

# Pass all arguments directly to kopia command in storage namespace
kubectl exec -n storage deploy/kopia -- kopia "$@"
