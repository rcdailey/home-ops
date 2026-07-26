"""Root CLI group with auto-discovery of subcommand modules."""

from __future__ import annotations

import click

from paperless._click import AutoGroup


@click.group(
    cls=AutoGroup,
    package="paperless",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(
    version=__import__("paperless").__version__, prog_name="paperless"
)
def cli():
    """LLM-optimized Paperless-ngx document management CLI."""
