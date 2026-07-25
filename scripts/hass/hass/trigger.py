"""Trigger automations or run scripts directly."""

from __future__ import annotations

import json

import click

from hass._client import run_ws
from hass._errors import HassError, die
from hass.call import call_service


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
        if variables:
            die("--vars is only supported for scripts")
        domain, service, entities, data = "automation", "trigger", [entity_id], {}
    elif entity_id.startswith("script."):
        domain = "script"
        service = entity_id.removeprefix("script.")
        entities = []
        data = json.loads(variables) if variables else {}
    else:
        die(f"entity_id must start with 'automation.' or 'script.': {entity_id}")

    async def handler(send):
        await call_service(send, domain, service, entities, data)
        click.echo(f"Triggered: {entity_id}")

    try:
        run_ws(handler)
    except HassError as exc:
        die(str(exc))
