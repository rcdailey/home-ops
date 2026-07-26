"""Root CLI group with auto-discovery of domain modules."""

from __future__ import annotations

import click

from hops._click import AutoGroup


@click.group(
    cls=AutoGroup,
    package="hops",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(version=__import__("hops").__version__, prog_name="hops")
def cli():
    """LLM-optimized cluster operations CLI."""
