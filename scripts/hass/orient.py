"""Discover entities, automations, scripts, and dashboard cards for a topic."""

from __future__ import annotations

import json
import re

import click

from hass._client import get_client, run_ws


@click.command()
@click.argument("terms", nargs=-1, required=True)
def cli(terms: tuple[str, ...]) -> None:
    """Search entities, automations, scripts, and dashboards for TERMS."""
    pattern = re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE)

    with get_client() as client:
        states = client.get_states()
        matches = [
            s
            for s in states
            if pattern.search(s.entity_id)
            or pattern.search(s.attributes.get("friendly_name", ""))
        ]
        entity_ids = {s.entity_id for s in matches}

        click.echo("## Entities")
        for s in sorted(matches, key=lambda x: x.entity_id):
            name = s.attributes.get("friendly_name", "")
            click.echo(f"  {s.entity_id}: {s.state}  ({name})")

        automations = [s for s in states if s.entity_id.startswith("automation.")]
        click.echo("\n## Automations")
        found = False
        for a in automations:
            config_id = a.attributes.get("id")
            if not config_id:
                continue
            try:
                config = client.request(f"config/automation/config/{config_id}")
            except Exception:
                continue
            config_str = json.dumps(config)
            if any(eid in config_str for eid in entity_ids) or pattern.search(
                config_str
            ):
                found = True
                alias = config.get("alias", a.entity_id)
                click.echo(f"\n### {alias} ({a.entity_id}, state: {a.state})")
                click.echo(json.dumps(config, indent=2))
        if not found:
            click.echo("  (none found)")

        # Script service slugs (entity_id can diverge from slug in HA)
        try:
            all_services = client.request("services")
            script_slugs = [
                slug
                for svc in all_services
                if svc.get("domain") == "script"
                for slug in svc.get("services", {})
                if slug not in ("reload", "turn_on", "turn_off", "toggle")
            ]
        except Exception:
            script_slugs = []
        click.echo("\n## Scripts")
        found = False
        for slug in script_slugs:
            try:
                config = client.request(f"config/script/config/{slug}")
            except Exception:
                continue
            config_str = json.dumps(config)
            if any(eid in config_str for eid in entity_ids) or pattern.search(
                config_str
            ):
                found = True
                alias = config.get("alias", slug)
                click.echo(f"\n### {alias} (script.{slug})")
                click.echo(json.dumps(config, indent=2))
        if not found:
            click.echo("  (none found)")

    async def search_dashboards(send):
        msg = await send({"type": "lovelace/dashboards/list"})
        dashboards = msg.get("result", [])

        configs: list[tuple[str, dict]] = []
        msg = await send({"type": "lovelace/config"})
        configs.append(("default", msg.get("result", {})))
        for d in dashboards:
            url_path = d.get("url_path")
            if not url_path:
                continue
            msg = await send({"type": "lovelace/config", "url_path": url_path})
            result = msg.get("result")
            if isinstance(result, dict):
                configs.append((url_path, result))

        hits = []

        def search_cards(obj, path, dashboard_name, view_title):
            if isinstance(obj, dict):
                entity = obj.get("entity", "")
                if isinstance(entity, str) and (
                    entity in entity_ids or pattern.search(entity)
                ):
                    name = obj.get("name", "")
                    hits.append((dashboard_name, view_title, path, entity, name))
                for k, v in obj.items():
                    search_cards(v, f"{path}.{k}", dashboard_name, view_title)
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    search_cards(v, f"{path}[{i}]", dashboard_name, view_title)

        for dash_name, config in configs:
            for view in config.get("views", []):
                view_title = view.get("title", "(untitled)")
                search_cards(view, "view", dash_name, view_title)

        return hits

    click.echo("\n## Dashboard Cards")
    hits = run_ws(search_dashboards)
    if hits:
        for dash, view, path, entity, name in hits:
            label = f"{name} ({entity})" if name else entity
            click.echo(f"  [{dash}] {view} > {label}")
    else:
        click.echo("  (none found)")
