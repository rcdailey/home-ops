"""Inspect devices and rename them the way the HA UI does."""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from typing import Any

import click
from slugify import slugify

from hass._client import Send, rest_get, run_ws, ws_error
from hass._errors import HassError, die
from hass._lovelace import fetch_config


@click.group()
def cli() -> None:
    """Inspect and rename devices."""


def device_name(device: dict) -> str:
    """The user-facing device name (registry override wins)."""
    return device.get("name_by_user") or device.get("name") or "(unnamed)"


def _slug(name: str) -> str:
    """Slugify the way HA does when it derives an object_id from a name."""
    return slugify(name, separator="_")


async def _registries(send: Send) -> tuple[list[dict], list[dict]]:
    devices = await send({"type": "config/device_registry/list"})
    if not devices.get("success"):
        raise HassError(ws_error(devices))
    entities = await send({"type": "config/entity_registry/list"})
    if not entities.get("success"):
        raise HassError(ws_error(entities))
    return devices["result"], entities["result"]


def resolve_device(devices: list[dict], query: str) -> dict:
    """Resolve a device by device_id or name (exact, then substring)."""
    by_id = {d["id"]: d for d in devices}
    if query in by_id:
        return by_id[query]

    want = query.strip().casefold()
    matches = [d for d in devices if device_name(d).casefold() == want]
    if not matches:
        matches = [d for d in devices if want in device_name(d).casefold()]
    if len(matches) == 1:
        return matches[0]

    if matches:
        found = "; ".join(f"{device_name(d)} [{d['id']}]" for d in matches)
        raise HassError(f"ambiguous device '{query}': {found}")

    names = sorted({device_name(d) for d in devices})
    close = difflib.get_close_matches(query, names, n=10, cutoff=0.4)
    listed = "; ".join(close or names[:10])
    raise HassError(
        f"no device matching '{query}' ({len(devices)} devices); candidates: {listed}"
    )


def plan_entity_ids(entities: list[dict], old_slug: str, new_slug: str) -> list[dict]:
    """Map each device entity to its new entity_id, or None when left alone."""
    plan = []
    for entry in sorted(entities, key=lambda e: e["entity_id"]):
        domain, _, object_id = entry["entity_id"].partition(".")
        if object_id == old_slug:
            new_object_id = new_slug
        elif object_id.startswith(f"{old_slug}_"):
            new_object_id = new_slug + object_id[len(old_slug) :]
        else:
            new_object_id = None
        plan.append(
            {
                "entity_id": entry["entity_id"],
                "new_entity_id": (
                    f"{domain}.{new_object_id}" if new_object_id else None
                ),
                "name_override": entry.get("name"),
            }
        )
    return plan


def _walk(obj: Any, ids: set[str], path: str, hits: list[tuple[str, str]]) -> None:
    if isinstance(obj, str):
        for eid in ids:
            if eid in obj:
                hits.append((eid, path))
    elif isinstance(obj, dict):
        for key, value in obj.items():
            _walk(value, ids, f"{path}.{key}", hits)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _walk(value, ids, f"{path}[{i}]", hits)


async def dashboard_refs(send: Send, ids: set[str]) -> list[dict]:
    """Find every dashboard view referencing any of ``ids``."""
    msg = await send({"type": "lovelace/dashboards/list"})
    url_paths = [d["url_path"] for d in msg.get("result", []) if d.get("url_path")]
    # The default (url_path-less) dashboard is the same stored config as the
    # dashboard whose url_path is `lovelace`, so drop the duplicate by content.
    url_paths.append(None)

    refs = []
    seen: set[str] = set()
    for url_path in url_paths:
        try:
            config = await fetch_config(send, url_path)
        except HassError:
            continue  # storage-mode config absent (YAML or auto-generated dashboard)
        digest = json.dumps(config, sort_keys=True)
        if digest in seen:
            continue
        seen.add(digest)
        for index, view in enumerate(config.get("views", [])):
            hits: list[tuple[str, str]] = []
            _walk(view, ids, "view", hits)
            if hits:
                refs.append(
                    {
                        "dashboard": url_path or "(default)",
                        "view": view.get("title") or f"#{index}",
                        "entities": sorted({eid for eid, _ in hits}),
                        "count": len(hits),
                    }
                )
    return refs


def config_refs(entities: list[dict], ids: set[str]) -> list[dict]:
    """Find automations and scripts whose stored config mentions any of ``ids``.

    A storage-mode automation's registry ``unique_id`` is its config UUID and a
    script's is its config slug, so the registry alone addresses every editable
    config; YAML-mode objects have no config endpoint and are not scanned.
    """
    refs = []
    for entry in entities:
        domain, _, _ = entry["entity_id"].partition(".")
        if domain not in ("automation", "script") or not entry.get("unique_id"):
            continue
        config = rest_get(f"config/{domain}/config/{entry['unique_id']}")
        if config is None:
            continue
        text = json.dumps(config)
        found = sorted(eid for eid in ids if eid in text)
        if found:
            refs.append(
                {
                    "kind": domain,
                    "entity_id": entry["entity_id"],
                    "alias": config.get("alias", entry["entity_id"]),
                    "entities": found,
                }
            )
    return refs


@dataclass
class RenamePlan:
    """Everything a device rename would change, plus what references it today."""

    device: dict
    old_name: str
    new_name: str
    old_slug: str
    new_slug: str
    entities: list[dict]
    conflicts: list[str]
    dashboards: list[dict]
    registry: list[dict]
    configs: list[dict] = field(default_factory=list)

    def as_dict(self, dry_run: bool) -> dict:
        return {
            "device_id": self.device["id"],
            "old_name": self.old_name,
            "new_name": self.new_name,
            "old_slug": self.old_slug,
            "new_slug": self.new_slug,
            "entities": self.entities,
            "conflicts": self.conflicts,
            "dashboard_refs": self.dashboards,
            "config_refs": self.configs,
            "dry_run": dry_run,
        }


def _print_plan(plan: RenamePlan, keep_entity_ids: bool) -> None:
    click.echo(f"device {plan.device['id']}: {plan.old_name} -> {plan.new_name}")
    click.echo(f"slug: {plan.old_slug} -> {plan.new_slug}")
    for item in plan.entities:
        if item["new_entity_id"]:
            line = f"  {item['entity_id']} -> {item['new_entity_id']}"
        else:
            reason = (
                "entity_ids kept"
                if keep_entity_ids
                else f"object_id lacks '{plan.old_slug}' prefix"
            )
            line = f"  {item['entity_id']} unchanged ({reason})"
        if item["name_override"]:
            line += f"; clear name override '{item['name_override']}'"
        click.echo(line)
    for ref in plan.dashboards:
        click.echo(
            f"  ref dashboard {ref['dashboard']} / {ref['view']}: "
            f"{ref['count']}x {' '.join(ref['entities'])}"
        )
    for ref in plan.configs:
        click.echo(
            f"  ref {ref['kind']} {ref['entity_id']} ({ref['alias']}): "
            f"{' '.join(ref['entities'])}"
        )
    if not plan.dashboards and not plan.configs:
        click.echo("  no dashboard/automation/script references")


@cli.command("list")
@click.argument("query", required=False)
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def list_cmd(query: str | None, as_json: bool) -> None:
    """List devices (optionally filtered by name/id substring) with entity counts."""

    async def handler(send):
        devices, entities = await _registries(send)
        counts: dict[str, int] = {}
        for entry in entities:
            if entry.get("device_id"):
                counts[entry["device_id"]] = counts.get(entry["device_id"], 0) + 1

        want = (query or "").strip().casefold()
        rows = [
            {
                "device_id": d["id"],
                "name": device_name(d),
                "area_id": d.get("area_id"),
                "model": " ".join(
                    p for p in (d.get("manufacturer"), d.get("model")) if p
                ),
                "entities": counts.get(d["id"], 0),
                "disabled_by": d.get("disabled_by"),
            }
            for d in devices
            if not want or want in device_name(d).casefold() or want in d["id"]
        ]
        rows.sort(key=lambda r: r["name"].casefold())

        if as_json:
            click.echo(json.dumps(rows, indent=2))
            return
        if not rows:
            die(f"no device matching '{query}' ({len(devices)} devices)")
        for row in rows:
            area = row["area_id"] or "-"
            extra = " disabled" if row["disabled_by"] else ""
            click.echo(
                f"{row['name']}  [{row['device_id']}] "
                f"area={area} entities={row['entities']} "
                f"({row['model'] or '?'}){extra}"
            )

    try:
        run_ws(handler)
    except HassError as exc:
        die(str(exc))


@cli.command()
@click.argument("query")
@click.argument("new_name")
@click.option("--dry-run", is_flag=True, help="Show the plan without writing")
@click.option(
    "--keep-entity-ids", is_flag=True, help="Rename the device only, leave entity_ids"
)
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def rename(
    query: str, new_name: str, dry_run: bool, keep_entity_ids: bool, as_json: bool
) -> None:
    """Rename device QUERY to NEW_NAME, cascading into its entity_ids.

    Mirrors the HA UI: the device gets a user-facing name, entity_ids derived from
    the old device name are re-slugified, and stale per-entity name overrides are
    cleared so entities inherit from the device again.
    """

    async def plan_handler(send):
        devices, entities = await _registries(send)
        device = resolve_device(devices, query)
        old_name = device_name(device)
        old_slug, new_slug = _slug(old_name), _slug(new_name)
        owned = [e for e in entities if e.get("device_id") == device["id"]]
        items = plan_entity_ids(owned, old_slug, new_slug)
        if keep_entity_ids:
            for item in items:
                item["new_entity_id"] = None

        taken = {e["entity_id"] for e in entities} - {i["entity_id"] for i in items}
        moving = {i["entity_id"] for i in items if i["new_entity_id"]}
        return RenamePlan(
            device=device,
            old_name=old_name,
            old_slug=old_slug,
            new_name=new_name,
            new_slug=new_slug,
            entities=items,
            conflicts=[
                i["new_entity_id"] for i in items if i["new_entity_id"] in taken
            ],
            dashboards=await dashboard_refs(send, moving) if moving else [],
            registry=entities,
        )

    async def write_handler(send):
        msg = await send(
            {
                "type": "config/device_registry/update",
                "device_id": plan.device["id"],
                "name_by_user": new_name,
            }
        )
        if not msg.get("success"):
            raise HassError(ws_error(msg))
        failures = []
        for item in plan.entities:
            payload: dict = {
                "type": "config/entity_registry/update",
                "entity_id": item["entity_id"],
            }
            if item["new_entity_id"]:
                payload["new_entity_id"] = item["new_entity_id"]
            if item["name_override"]:
                payload["name"] = None
            if len(payload) == 2:
                continue
            msg = await send(payload)
            if not msg.get("success"):
                failures.append((item["entity_id"], ws_error(msg)))
        return failures

    try:
        plan = run_ws(plan_handler)
        moving = {i["entity_id"] for i in plan.entities if i["new_entity_id"]}
        plan.configs = config_refs(plan.registry, moving) if moving else []

        if as_json:
            click.echo(json.dumps(plan.as_dict(dry_run), indent=2))
        else:
            _print_plan(plan, keep_entity_ids)

        if plan.conflicts:
            die(f"entity_id already in use: {' '.join(plan.conflicts)}")
        if dry_run:
            if not as_json:
                click.echo("dry-run: nothing written")
            return

        for entity_id, error in run_ws(write_handler):
            click.echo(f"{entity_id}: FAILED - {error}", err=True)
        click.echo("written; references listed above must be updated by hand")
    except HassError as exc:
        die(str(exc))
