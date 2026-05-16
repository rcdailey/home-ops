"""Flux domain: GitOps reconciliation status and diagnostics."""

from __future__ import annotations

import click

from hops._click import HelpfulGroup


@click.group(cls=HelpfulGroup)
def cli():
    """Flux GitOps status and diagnostics."""


# Import submodules after cli is defined; @cli.command decorators register against this group.
from hops.flux import status as _status  # noqa: E402, F401
from hops.flux import toggle as _toggle  # noqa: E402, F401
