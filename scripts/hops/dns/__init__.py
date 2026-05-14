"""DNS domain: Blocky DNS query log analysis (port of blocky.py)."""

from __future__ import annotations

import click


@click.group()
def cli():
    """Blocky DNS query log analysis."""


# Import submodules after cli is defined; @cli.command decorators register against this group.
from hops.dns import commands as _commands  # noqa: E402, F401
