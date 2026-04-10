#!/usr/bin/env -S uv run --quiet --project scripts/hops --python 3.13
"""Entry point for hops CLI. Run from repo root: ./scripts/hops.py"""

from hops.cli import cli

cli()
