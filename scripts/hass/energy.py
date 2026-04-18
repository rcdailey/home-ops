"""Energy dashboard configuration."""

from __future__ import annotations

import json

import click

from hass._client import die, print_json, run_ws, ws_error


@click.group(invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
@click.pass_context
def cli(ctx: click.Context, as_json: bool) -> None:
    """Show or modify the Energy dashboard configuration."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(get_cmd, as_json=as_json)


def _get_prefs() -> dict:
    result: dict = {}

    async def handler(send):
        msg = await send({"type": "energy/get_prefs"})
        if not msg.get("success"):
            die(f"Error: {ws_error(msg)}")
        result.update(msg["result"])

    run_ws(handler)
    return result


def _save_prefs(prefs: dict) -> None:
    async def handler(send):
        payload = {"type": "energy/save_prefs", **prefs}
        msg = await send(payload)
        if not msg.get("success"):
            die(f"Save failed: {ws_error(msg)}")

    run_ws(handler)


@cli.command("get")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def get_cmd(as_json: bool) -> None:
    """Show the current energy config."""
    prefs = _get_prefs()
    if as_json:
        print_json(prefs)
        return

    sources = prefs.get("energy_sources", [])
    devices = prefs.get("device_consumption", [])

    click.echo("## Energy Sources")
    if not sources:
        click.echo("  (none)")
    for s in sources:
        src_type = s.get("type", "unknown")
        if src_type == "grid":
            parts = [f"  grid: import={s.get('stat_energy_from', '(none)')}"]
            if s.get("stat_energy_to"):
                parts.append(f"export={s['stat_energy_to']}")
            if s.get("entity_energy_price"):
                parts.append(f"price={s['entity_energy_price']}")
            elif s.get("number_energy_price"):
                parts.append(f"price=${s['number_energy_price']}")
            click.echo(", ".join(parts))
        elif src_type == "solar":
            click.echo(f"  solar: {s.get('stat_energy_from', '(none)')}")
        elif src_type == "battery":
            click.echo(
                f"  battery: from={s.get('stat_energy_from')}, to={s.get('stat_energy_to')}"
            )
        else:
            click.echo(f"  {src_type}: {s.get('stat_energy_from', json.dumps(s))}")

    click.echo("\n## Device Consumption")
    if not devices:
        click.echo("  (none)")
    for d in devices:
        stat = d["stat_consumption"]
        name = d.get("name", "")
        label = f"{stat} ({name})" if name else stat
        click.echo(f"  {label}")

    water = prefs.get("device_consumption_water", [])
    if water:
        click.echo("\n## Water Consumption")
        for d in water:
            click.echo(f"  {d['stat_consumption']}")


@cli.command("validate")
def validate_cmd() -> None:
    """Report broken entity references in the energy config."""
    result: dict = {}

    async def handler(send):
        msg = await send({"type": "energy/validate"})
        result.update(msg.get("result", {}))

    run_ws(handler)

    issues = []
    for section in ("energy_sources", "device_consumption", "device_consumption_water"):
        for i, entry_issues in enumerate(result.get(section, [])):
            for issue in entry_issues:
                affected = issue.get("affected_entities", [])
                entities = [e[0] for e in affected if e]
                issues.append(
                    {
                        "section": section,
                        "index": i,
                        "type": issue["type"],
                        "entities": entities,
                    }
                )
    if not issues:
        click.echo("(valid)")
        return
    for issue in issues:
        ents = ", ".join(issue["entities"]) if issue["entities"] else ""
        click.echo(f"{issue['section']}[{issue['index']}]: {issue['type']}  {ents}")


@cli.group("device")
def device_group() -> None:
    """Manage device consumption entries."""


@device_group.command("add")
@click.argument("entity_id")
def device_add(entity_id: str) -> None:
    """Add ENTITY_ID as a device consumption sensor."""
    prefs = _get_prefs()
    devices = prefs.get("device_consumption", [])
    if entity_id in {d["stat_consumption"] for d in devices}:
        click.echo(f"Already present: {entity_id}")
        return
    devices.append({"stat_consumption": entity_id})
    prefs["device_consumption"] = devices
    _save_prefs(prefs)
    click.echo(f"Added: {entity_id}")


@device_group.command("remove")
@click.argument("entity_id")
def device_remove(entity_id: str) -> None:
    """Remove ENTITY_ID from device consumption."""
    prefs = _get_prefs()
    devices = prefs.get("device_consumption", [])
    filtered = [d for d in devices if d["stat_consumption"] != entity_id]
    if len(filtered) == len(devices):
        die(f"Not found: {entity_id}")
    prefs["device_consumption"] = filtered
    _save_prefs(prefs)
    click.echo(f"Removed: {entity_id}")


@device_group.command("replace")
@click.argument("old")
@click.argument("new")
def device_replace(old: str, new: str) -> None:
    """Replace OLD entity_id with NEW in device consumption."""
    prefs = _get_prefs()
    devices = prefs.get("device_consumption", [])
    found = False
    for d in devices:
        if d["stat_consumption"] == old:
            d["stat_consumption"] = new
            found = True
            break
    if not found:
        die(f"Not found: {old}")
    prefs["device_consumption"] = devices
    _save_prefs(prefs)
    click.echo(f"Replaced: {old} -> {new}")
