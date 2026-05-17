#!/usr/bin/env -S uv run --quiet --project scripts/paperless --python 3.13
"""Entry point for paperless CLI. Run from repo root: ./scripts/paperless.py"""

from paperless.cli import cli

cli()
