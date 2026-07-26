"""DNS domain: Blocky DNS query log analysis (port of blocky.py)."""

from __future__ import annotations

import click

from hops._click import AutoGroup


@click.group(cls=AutoGroup, package="hops.dns")
def cli():
    """Blocky DNS query log analysis."""
