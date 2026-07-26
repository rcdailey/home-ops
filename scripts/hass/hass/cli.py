"""Root CLI group with auto-discovery of subcommand modules."""

from __future__ import annotations

import click

from hass._click import AutoGroup


@click.group(
    cls=AutoGroup,
    package="hass",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(version=__import__("hass").__version__, prog_name="hass")
def cli():
    """Home Assistant API wrapper."""
