"""Document classification workflow."""

from __future__ import annotations

import click

from paperless._click import AutoGroup


@click.group(cls=AutoGroup, package="paperless.classify")
def cli() -> None:
    """AI-assisted document classification workflow."""
