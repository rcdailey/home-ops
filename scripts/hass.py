#!/usr/bin/env -S uv run --quiet --project scripts/hass --python 3.13
"""Entry point for the hass CLI. Run from repo root: ./scripts/hass.py"""

from hass.cli import cli

cli()
