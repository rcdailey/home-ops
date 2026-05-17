"""Document management domain."""

from __future__ import annotations

import click

from paperless._click import HelpfulGroup


@click.group(cls=HelpfulGroup)
def cli() -> None:
    """List, search, upload, update, and inspect documents."""


from paperless.doc import commands as _commands  # noqa: E402, F401
