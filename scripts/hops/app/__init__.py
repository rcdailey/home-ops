"""App domain: application listing, debugging, and diagnostics."""

from __future__ import annotations

import click


@click.group()
def cli():
    """Application listing, logs, and diagnostics."""


# Import submodules after cli is defined; @cli.command decorators register against this group.
from hops.app import cluster as _cluster  # noqa: E402, F401
from hops.app import commands as _commands  # noqa: E402, F401
