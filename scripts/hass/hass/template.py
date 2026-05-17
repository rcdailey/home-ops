"""Render Jinja2 templates against HA state."""

from __future__ import annotations

import click

from hass._client import get_client


@click.command()
@click.argument("source")
def cli(source: str) -> None:
    """Render a Jinja2 template via the HA /api/template endpoint."""
    with get_client() as client:
        click.echo(client.get_rendered_template(source))
