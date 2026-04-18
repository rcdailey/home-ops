"""Trigger automations or run scripts directly."""

from __future__ import annotations

import json

import click

from hass._client import die, get_client


@click.command()
@click.argument("entity_id")
@click.option(
    "--vars",
    "variables",
    help="JSON object of script variables (scripts only)",
)
def cli(entity_id: str, variables: str | None) -> None:
    """Trigger automation.foo or run script.foo.

    Examples:

      hass trigger automation.my_automation
      hass trigger script.set_mode --vars '{"hdr_mode": "user_4"}'
    """
    if entity_id.startswith("automation."):
        service = "automation/trigger"
        payload = {"entity_id": entity_id}
        if variables:
            die("Error: --vars is only supported for scripts")
    elif entity_id.startswith("script."):
        slug = entity_id.removeprefix("script.")
        service = f"script/{slug}"
        payload = json.loads(variables) if variables else {}
    else:
        die(f"Error: entity_id must start with 'automation.' or 'script.': {entity_id}")

    with get_client() as client:
        client.request(f"services/{service}", method="POST", json=payload)
    click.echo(f"Triggered: {entity_id}")
