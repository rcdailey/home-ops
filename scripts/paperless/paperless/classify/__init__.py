"""Document classification workflow."""

from __future__ import annotations

import click

from paperless._click import HelpfulGroup


@click.group(cls=HelpfulGroup)
def cli() -> None:
    """AI-assisted document classification workflow."""


from paperless.classify import commands as _commands  # noqa: E402, F401
