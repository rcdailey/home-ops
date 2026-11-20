#!/usr/bin/env bash
exec uv run --quiet \
  --project "$(dirname "$(realpath "$0")")/opensprinkler" \
  -m opensprinkler "$@"
