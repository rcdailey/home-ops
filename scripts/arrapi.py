#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["click", "httpx"]
# ///
"""CLI for querying and mutating Sonarr/Radarr instances via their APIs.

Instances are resolved by name. API keys and domain are read from environment
variables; nothing is hardcoded or stored on disk.

Examples:
    arrapi.py instances
    arrapi.py get sonarr /api/v3/system/status
    arrapi.py get --all /api/v3/indexer
    arrapi.py put radarr /api/v3/indexer/17 -d '{"id": 17, ...}'
    arrapi.py indexers --all
    arrapi.py fix-seeds --all --dry-run
"""

import json
import os
import sys

import click
import httpx

# ---------------------------------------------------------------------------
# Instance registry
# ---------------------------------------------------------------------------

INSTANCES: dict[str, dict] = {
    "sonarr": {
        "key_env": "SONARR_API_KEY",
        "host": "sonarr",
        "type": "sonarr",
    },
    "sonarr-anime": {
        "key_env": "SONARR_ANIME_API_KEY",
        "host": "sonarr-anime",
        "type": "sonarr",
    },
    "radarr": {
        "key_env": "RADARR_API_KEY",
        "host": "radarr",
        "type": "radarr",
    },
    "radarr-4k": {
        "key_env": "RADARR_4K_API_KEY",
        "host": "radarr-4k",
        "type": "radarr",
    },
    "radarr-anime": {
        "key_env": "RADARR_ANIME_API_KEY",
        "host": "radarr-anime",
        "type": "radarr",
    },
}

INSTANCE_NAMES = list(INSTANCES.keys())


def _domain() -> str:
    d = os.environ.get("SECRET_DOMAIN", "")
    if not d:
        click.echo("Error: SECRET_DOMAIN env var is required", err=True)
        raise SystemExit(1)
    return d


def _resolve(name: str) -> dict:
    """Resolve an instance name to its config with API key."""
    if name not in INSTANCES:
        click.echo(
            f"Unknown instance '{name}'. Available: {', '.join(INSTANCE_NAMES)}",
            err=True,
        )
        raise SystemExit(1)
    inst = INSTANCES[name]
    api_key = os.environ.get(inst["key_env"], "")
    if not api_key:
        click.echo(f"Error: {inst['key_env']} env var is required", err=True)
        raise SystemExit(1)
    return {**inst, "api_key": api_key, "name": name}


def _targets(
    instance: str | None, all_instances: bool, type_filter: str | None = None
) -> list[dict]:
    """Build list of target instances from CLI options."""
    if all_instances:
        targets = [_resolve(n) for n in INSTANCE_NAMES]
        if type_filter:
            targets = [t for t in targets if t["type"] == type_filter]
        return targets
    if not instance:
        click.echo("Error: provide an instance name or --all", err=True)
        raise SystemExit(1)
    return [_resolve(instance)]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _client(inst: dict) -> httpx.Client:
    return httpx.Client(
        base_url=f"https://{inst['host']}.{_domain()}",
        headers={"X-Api-Key": inst["api_key"]},
        timeout=30,
    )


def _request(inst: dict, method: str, path: str, body: dict | None = None):
    with _client(inst) as c:
        kwargs = {}
        if body is not None:
            kwargs["json"] = body
        r = c.request(method, path, **kwargs)
        r.raise_for_status()
        return r.json() if r.content else None


def _out(data):
    click.echo(json.dumps(data, indent=2))


def _banner(inst: dict):
    click.echo(f"\n{'=' * 60}")
    click.echo(f"  {inst['name']} ({inst['type']})")
    click.echo(f"{'=' * 60}")


def _read_body(data: str | None) -> dict | None:
    """Parse JSON body from --data flag or stdin."""
    if data:
        return json.loads(data)
    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            return json.loads(raw)
    return None


# ---------------------------------------------------------------------------
# Shared CLI options
# ---------------------------------------------------------------------------

INSTANCE_ARG = click.argument(
    "instance", type=click.Choice(INSTANCE_NAMES), required=False
)
ALL_OPT = click.option(
    "--all", "all_instances", is_flag=True, help="Run against all instances"
)
TYPE_OPT = click.option(
    "--type",
    "type_filter",
    type=click.Choice(["sonarr", "radarr"]),
    default=None,
    help="Filter --all to one instance type",
)
DATA_OPT = click.option(
    "--data", "-d", default=None, help="JSON body (or pipe via stdin)"
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
def cli():
    """Sonarr/Radarr API client."""


@cli.command("instances")
def list_instances():
    """List configured instances and API key status."""
    domain = _domain()
    for name, cfg in INSTANCES.items():
        key_set = "set" if os.environ.get(cfg["key_env"]) else "MISSING"
        click.echo(f"  {name:<16} {cfg['type']:<8} {cfg['host']}.{domain}  [{key_set}]")


# -- HTTP verb commands -----------------------------------------------------


def _http_command(method: str):
    """Factory for GET/POST/PUT/DELETE commands."""

    @cli.command(method.lower())
    @INSTANCE_ARG
    @ALL_OPT
    @TYPE_OPT
    @click.argument("path")
    @DATA_OPT
    def cmd(instance, all_instances, type_filter, path, data):
        body = _read_body(data) if method in ("PUT", "POST") else None
        targets = _targets(instance, all_instances, type_filter)
        multi = len(targets) > 1
        for inst in targets:
            if multi:
                _banner(inst)
            result = _request(inst, method, path, body)
            if result is not None:
                _out(result)

    cmd.__doc__ = (
        f"{method} request: arrapi.py {method.lower()} <instance|--all> <path>"
    )
    return cmd


_http_command("GET")
_http_command("POST")
_http_command("PUT")
_http_command("DELETE")


# -- Indexer commands -------------------------------------------------------


@cli.group()
def indexer():
    """Indexer management commands."""


@indexer.command("list")
@INSTANCE_ARG
@ALL_OPT
@TYPE_OPT
def indexer_list(instance, all_instances, type_filter):
    """List indexers with seed settings."""
    for inst in _targets(instance, all_instances, type_filter):
        _banner(inst)
        for idx in _request(inst, "GET", "/api/v3/indexer"):
            name = idx.get("name", "?")
            idx_id = idx.get("id", "?")
            fields = {f["name"]: f.get("value") for f in idx.get("fields", [])}

            seed_ratio = fields.get("seedCriteria.seedRatio")
            seed_time = fields.get("seedCriteria.seedTime")
            pack_time = fields.get(
                "seedCriteria.seasonPackSeedTime",
                fields.get("seedCriteria.packSeedTime"),
            )

            def fmt(v):
                return v if v is not None else "(default)"

            click.echo(f"\n  [{idx_id}] {name}")
            click.echo(f"    seedRatio: {fmt(seed_ratio)}")
            click.echo(f"    seedTime: {fmt(seed_time)}")
            click.echo(f"    packTime: {fmt(pack_time)}")


@indexer.command("fix-seeds")
@INSTANCE_ARG
@ALL_OPT
@TYPE_OPT
@click.option("--dry-run", is_flag=True, help="Show changes without applying")
def indexer_fix_seeds(instance, all_instances, type_filter, dry_run):
    """Clear per-indexer seed ratio/time overrides (fall back to client defaults)."""
    seed_fields = {
        "seedCriteria.seedRatio",
        "seedCriteria.seedTime",
        "seedCriteria.seasonPackSeedTime",
        "seedCriteria.packSeedTime",
    }

    for inst in _targets(instance, all_instances, type_filter):
        _banner(inst)
        for idx in _request(inst, "GET", "/api/v3/indexer"):
            name = idx.get("name", "?")
            idx_id = idx.get("id", "?")
            changed = False

            for field in idx.get("fields", []):
                if field["name"] in seed_fields and field.get("value") is not None:
                    old = field["value"]
                    click.echo(
                        f"  [{idx_id}] {name}: {field['name']} = {old} -> (cleared)"
                    )
                    field["value"] = None
                    changed = True

            if changed and not dry_run:
                _request(inst, "PUT", f"/api/v3/indexer/{idx_id}", idx)
                click.echo(f"  [{idx_id}] {name}: updated")
            elif not changed:
                click.echo(f"  [{idx_id}] {name}: clean")


if __name__ == "__main__":
    cli()
