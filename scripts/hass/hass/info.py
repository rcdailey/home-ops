"""Report Home Assistant instance version, config, and inventory counts."""

from __future__ import annotations

import json
from collections import Counter

import click

from hass._client import run_ws, ws_error
from hass._errors import die


@click.command()
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def cli(as_json: bool) -> None:
    """Show instance version, core config, and inventory counts."""

    async def handler(send):
        msg = await send({"type": "get_config"})
        if not msg.get("success"):
            die(f"Error: {ws_error(msg)}")
        config = msg["result"]

        entries = (await send({"type": "config_entries/get"})).get("result", [])
        devices = (await send({"type": "config/device_registry/list"})).get(
            "result", []
        )
        entities = (await send({"type": "config/entity_registry/list"})).get(
            "result", []
        )
        flows = (await send({"type": "config_entries/flow/progress"})).get("result", [])
        dashboards = (await send({"type": "lovelace/dashboards/list"})).get(
            "result", []
        )
        issues = (await send({"type": "repairs/list_issues"})).get("result", {})
        repairs = [i for i in issues.get("issues", []) if not i.get("ignored")]

        states = Counter(e.get("state", "?") for e in entries)
        info = {
            "version": config.get("version"),
            "state": config.get("state"),
            "location_name": config.get("location_name"),
            "time_zone": config.get("time_zone"),
            "country": config.get("country"),
            "language": config.get("language"),
            "config_source": config.get("config_source"),
            "external_url": config.get("external_url"),
            "internal_url": config.get("internal_url"),
            "safe_mode": config.get("safe_mode"),
            "recovery_mode": config.get("recovery_mode"),
            "components": len(config.get("components", [])),
            "config_entries": dict(states),
            "devices": len(devices),
            "entities": len(entities),
            "pending_flows": len(flows),
            "dashboards": len(dashboards) + 1,
            "repairs": len(repairs),
        }

        if as_json:
            click.echo(json.dumps(info, indent=2))
            return

        click.echo(
            f"Home Assistant {info['version']} ({info['state']}) "
            f"at {info['location_name']}, {info['time_zone']}"
        )
        click.echo(
            f"URLs: external={info['external_url']} internal={info['internal_url']}"
        )
        click.echo(
            f"Config: source={info['config_source']} country={info['country']} "
            f"language={info['language']} safe_mode={info['safe_mode']} "
            f"recovery_mode={info['recovery_mode']}"
        )
        entry_states = " ".join(f"{k}={v}" for k, v in sorted(states.items()))
        click.echo(
            f"Inventory: components={info['components']} devices={info['devices']} "
            f"entities={info['entities']} dashboards={info['dashboards']}"
        )
        click.echo(f"Config entries: {sum(states.values())} ({entry_states})")
        click.echo(f"Pending discovery flows: {info['pending_flows']}")
        click.echo(f"Active repairs: {info['repairs']}")

    run_ws(handler)
