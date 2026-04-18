"""Manage areas and entity area assignments."""

from __future__ import annotations

import click

from hass._client import die, run_ws, ws_error


@click.group()
def cli() -> None:
    """Manage areas and entity area assignments."""


@cli.command("list")
def list_cmd() -> None:
    """List all areas."""

    async def handler(send):
        msg = await send({"type": "config/area_registry/list"})
        areas = msg.get("result", [])
        for a in sorted(areas, key=lambda x: x["name"]):
            click.echo(f"  {a['area_id']:25s} {a['name']}")

    run_ws(handler)


@cli.command("get")
@click.argument("entity_id")
def get_cmd(entity_id: str) -> None:
    """Show an entity's area assignment."""

    async def handler(send):
        msg = await send({"type": "config/entity_registry/get", "entity_id": entity_id})
        if not msg.get("success"):
            die(f"Error: {ws_error(msg)}")
        entry = msg["result"]
        area = entry.get("area_id") or "(inherited from device)"
        device = entry.get("device_id", "")
        click.echo(f"{entry['entity_id']}: area={area}, device={device}")

    run_ws(handler)


@cli.command("create")
@click.argument("name")
def create_cmd(name: str) -> None:
    """Create a new area."""

    async def handler(send):
        msg = await send({"type": "config/area_registry/create", "name": name})
        if not msg.get("success"):
            die(f"Failed: {ws_error(msg)}")
        area = msg["result"]
        click.echo(f"Created: {area['area_id']} ({area['name']})")

    run_ws(handler)


@cli.command("set")
@click.argument("entity_ids")
@click.argument("area")
def set_cmd(entity_ids: str, area: str) -> None:
    """Assign ENTITY_IDS (comma-separated) to AREA (id or name)."""

    async def handler(send):
        msg = await send({"type": "config/area_registry/list"})
        areas = msg.get("result", [])
        area_map = {a["area_id"]: a for a in areas}
        name_map = {a["name"].lower(): a for a in areas}

        if area in area_map:
            area_id = area
        elif area.lower() in name_map:
            area_id = name_map[area.lower()]["area_id"]
        else:
            lines = [f"Error: area not found: {area}", "Available areas:"]
            for a in sorted(areas, key=lambda x: x["name"]):
                lines.append(f"  {a['area_id']:25s} {a['name']}")
            die("\n".join(lines))

        ids = [eid.strip() for eid in entity_ids.split(",") if eid.strip()]
        for eid in ids:
            msg = await send(
                {
                    "type": "config/entity_registry/update",
                    "entity_id": eid,
                    "area_id": area_id,
                }
            )
            if msg.get("success"):
                entry = msg["result"]["entity_entry"]
                new_area = entry.get("area_id", "(none)")
                click.echo(f"{eid}: area -> {new_area}")
            else:
                click.echo(f"{eid}: FAILED - {ws_error(msg)}", err=True)

    run_ws(handler)
