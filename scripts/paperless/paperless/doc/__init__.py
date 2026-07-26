"""Document management domain."""

from __future__ import annotations

import click

from paperless._click import AutoGroup


@click.group(cls=AutoGroup, package="paperless.doc")
def cli() -> None:
    """List, search, upload, update, and inspect documents."""
