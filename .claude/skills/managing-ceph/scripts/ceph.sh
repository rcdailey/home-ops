#!/usr/bin/env bash

# ceph.sh - Convenience wrapper for ceph commands via rook-ceph-tools pod

set -euo pipefail

# Pass all arguments directly to ceph command in tools pod
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph "$@"
