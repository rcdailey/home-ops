"""Flux domain: GitOps reconciliation status and diagnostics."""

from __future__ import annotations

import click

from hops._click import AutoGroup


@click.group(cls=AutoGroup, package="hops.flux")
def cli():
    """Flux GitOps status and diagnostics."""
