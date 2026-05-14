#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["click", "httpx"]
# ///
"""CLI for inspecting QUI (qBittorrent management) via its REST API."""

import json
import os
from pathlib import Path

import click
import httpx

SECRET_DOMAIN = os.environ.get("SECRET_DOMAIN", "")
BASE_URL = f"https://qui.{SECRET_DOMAIN}"
API_KEY = os.environ.get("QUI_API_KEY", "")


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        headers={"X-API-Key": API_KEY},
        timeout=30,
    )


def _check_env():
    if not SECRET_DOMAIN:
        click.echo("Error: SECRET_DOMAIN env var is required", err=True)
        raise SystemExit(1)
    if not API_KEY:
        click.echo("Error: QUI_API_KEY env var is required", err=True)
        raise SystemExit(1)


def _out(data):
    click.echo(json.dumps(data, indent=2))


def _get(path: str):
    with _client() as c:
        r = c.get(path)
        r.raise_for_status()
        return r.json()


def _post(path: str, body: dict | None = None):
    with _client() as c:
        r = c.post(path, json=body or {})
        r.raise_for_status()
        return r.json() if r.content else None


def _put(path: str, body: dict):
    with _client() as c:
        r = c.put(path, json=body)
        r.raise_for_status()
        return r.json() if r.content else None


@click.group()
def cli():
    """QUI API client."""
    _check_env()


# -- Instance commands --


@cli.command()
def instances():
    """List configured qBittorrent instances."""
    _out(_get("/api/instances"))


@cli.command("instance-info")
@click.argument("instance")
def instance_info(instance):
    """Get qBittorrent app info for an instance."""
    _out(_get(f"/api/instances/{instance}/app-info"))


@cli.command("instance-prefs")
@click.argument("instance")
def instance_prefs(instance):
    """Get qBittorrent preferences for an instance."""
    _out(_get(f"/api/instances/{instance}/preferences"))


@cli.command("transfer-info")
@click.argument("instance")
def transfer_info(instance):
    """Get transfer stats for an instance."""
    _out(_get(f"/api/instances/{instance}/transfer-info"))


# -- Torrent commands --


@cli.command()
@click.argument("instance")
@click.option("--limit", default=50, type=int)
@click.option("--offset", default=0, type=int)
@click.option("--sort", default="added_on")
@click.option("--reverse", is_flag=True)
@click.option("--filter", "state_filter", default=None, help="State filter")
@click.option("--category", default=None)
@click.option("--tag", default=None)
@click.option("--tracker", default=None)
def torrents(
    instance, limit, offset, sort, reverse, state_filter, category, tag, tracker
):
    """List torrents for an instance."""
    params = {
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "reverse": str(reverse).lower(),
    }
    if state_filter:
        params["filter"] = state_filter
    if category:
        params["category"] = category
    if tag:
        params["tag"] = tag
    if tracker:
        params["tracker"] = tracker
    _out(_get(f"/api/instances/{instance}/torrents?{httpx.QueryParams(params)}"))


@cli.command("torrent-trackers")
@click.argument("instance")
@click.argument("hash_")
def torrent_trackers(instance, hash_):
    """List trackers for a torrent."""
    _out(_get(f"/api/instances/{instance}/torrents/{hash_}/trackers"))


@cli.command("torrent-props")
@click.argument("instance")
@click.argument("hash_")
def torrent_props(instance, hash_):
    """Get torrent properties."""
    _out(_get(f"/api/instances/{instance}/torrents/{hash_}/properties"))


# -- Add torrent --


@cli.command("add-torrent")
@click.argument("instance")
@click.option("--url", default=None, help="Torrent download URL or magnet link")
@click.option(
    "--file",
    "filepath",
    default=None,
    type=click.Path(exists=True),
    help="Path to .torrent file",
)
@click.option("--category", default=None)
@click.option("--tags", default=None, help="Comma-separated tags")
@click.option("--savepath", default=None)
@click.option(
    "--content-layout",
    default=None,
    type=click.Choice(["Original", "Subfolder", "NoSubfolder"]),
)
@click.option("--paused", is_flag=True)
def add_torrent(
    instance, url, filepath, category, tags, savepath, content_layout, paused
):
    """Add a torrent to an instance via URL or file."""
    if not url and not filepath:
        raise click.UsageError("Either --url or --file is required.")

    data = {}
    files = {}

    if url:
        data["urls"] = url
    elif filepath:
        path = Path(filepath)
        files["torrent"] = (path.name, path.read_bytes(), "application/x-bittorrent")

    if category:
        data["category"] = category
    if tags:
        data["tags"] = tags
    if savepath:
        data["savepath"] = savepath
    if content_layout:
        data["contentLayout"] = content_layout
    if paused:
        data["paused"] = "true"

    with _client() as c:
        r = c.post(
            f"/api/instances/{instance}/torrents", data=data, files=files or None
        )
        if r.status_code >= 400:
            click.echo(f"HTTP {r.status_code}: {r.text}", err=True)
            raise SystemExit(1)
        result = r.json() if r.content else None
        click.echo(f"Added torrent (HTTP {r.status_code})")
        if result:
            _out(result)


# -- Automation commands --


@cli.command()
@click.argument("instance")
def automations(instance):
    """List automation rules for an instance."""
    _out(_get(f"/api/instances/{instance}/automations"))


@cli.command("automation-activity")
@click.argument("instance")
def automation_activity(instance):
    """List recent automation activity."""
    _out(_get(f"/api/instances/{instance}/automations/activity"))


@cli.command("automation-dry-run")
@click.argument("instance")
@click.option("--rule-id", default=None, help="Specific rule ID to dry-run")
def automation_dry_run(instance, rule_id):
    """Dry-run all automation rules."""
    body = {}
    if rule_id:
        body["ruleId"] = int(rule_id)
    _out(_post(f"/api/instances/{instance}/automations/dry-run", body))


@cli.command("automation-apply")
@click.argument("instance")
def automation_apply(instance):
    """Manually trigger automation rules to run now."""
    _out(_post(f"/api/instances/{instance}/automations/apply"))


@cli.command("automation-update")
@click.argument("instance")
@click.argument("rule_id")
@click.argument("file", type=click.Path(exists=True))
def automation_update(instance, rule_id, file):
    """Update an automation rule from a JSON file."""
    body = json.loads(Path(file).read_text())
    _out(_put(f"/api/instances/{instance}/automations/{rule_id}", body))


# -- Other commands --


@cli.command()
@click.argument("instance")
def categories(instance):
    """List categories for an instance."""
    _out(_get(f"/api/instances/{instance}/categories"))


@cli.command()
@click.argument("instance")
def tags(instance):
    """List tags for an instance."""
    _out(_get(f"/api/instances/{instance}/tags"))


@cli.command()
@click.argument("instance")
def trackers(instance):
    """List active trackers across all torrents."""
    _out(_get(f"/api/instances/{instance}/trackers"))


@cli.command("cross-seed-settings")
def cross_seed_settings():
    """Get cross-seed settings."""
    _out(_get("/api/cross-seed/settings"))


@cli.command("cross-seed-status")
def cross_seed_status():
    """Get cross-seed scheduler status."""
    _out(_get("/api/cross-seed/status"))


if __name__ == "__main__":
    cli()
