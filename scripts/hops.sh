#!/usr/bin/env bash
exec uv run --quiet \
  --project "$(dirname "$(realpath "$0")")/hops" \
  -m hops "$@"
