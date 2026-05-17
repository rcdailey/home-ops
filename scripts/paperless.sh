#!/usr/bin/env bash
exec uv run --quiet \
  --project "$(dirname "$(realpath "$0")")/paperless" \
  -m paperless "$@"
