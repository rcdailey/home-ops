"""App domain: application listing, debugging, and diagnostics."""

from __future__ import annotations

import click

from hops._click import AutoGroup


@click.group(cls=AutoGroup, package="hops.app")
def cli():
    """Application listing, logs, and diagnostics."""
