"""Enable or disable entities via the entity registry."""

from __future__ import annotations

import click

from hass._client import print_json, run_ws


@click.group()
def cli() -> None:
    """Enable/disable entities."""


def _set_disabled(entity_id: str, disabled_by: str | None) -> None:
    async def handler(send):
        msg = await send(
            {
                "type": "config/entity_registry/update",
                "entity_id": entity_id,
                "disabled_by": disabled_by,
            }
        )
        if msg.get("success"):
            entry = msg["result"]["entity_entry"]
            delay = msg["result"].get("reload_delay")
            status = "disabled" if entry.get("disabled_by") else "enabled"
            click.echo(f"{entry['entity_id']}: {status}")
            if delay:
                click.echo(f"Reload in {delay}s")
        else:
            print_json(msg)

    run_ws(handler)


@cli.command()
@click.argument("entity_id")
def enable(entity_id: str) -> None:
    """Enable an entity."""
    _set_disabled(entity_id, None)


@cli.command()
@click.argument("entity_id")
def disable(entity_id: str) -> None:
    """Disable an entity."""
    _set_disabled(entity_id, "user")
