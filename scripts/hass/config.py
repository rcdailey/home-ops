"""Get automation/script configuration."""

from __future__ import annotations

import click
from homeassistant_api.errors import EndpointNotFoundError

from hass._client import die, get_client, print_json, run_ws


@click.group()
def cli() -> None:
    """Get automation or script configuration (as JSON)."""


@cli.command("automation")
@click.argument("identifier")
def automation_cmd(identifier: str) -> None:
    """Fetch automation config by entity_id or UUID."""
    with get_client() as client:
        config_id = identifier
        if identifier.startswith("automation."):
            try:
                state = client.get_state(entity_id=identifier)
            except EndpointNotFoundError:
                die(f"Entity not found: {identifier}")
            config_id = state.attributes.get("id", "")
            if not config_id:
                die(f"Error: could not resolve automation id from {identifier}")
        resp = client.request(f"config/automation/config/{config_id}")
    print_json(resp)


def _resolve_script_slug(entity_id: str) -> str | None:
    """Resolve a script entity_id to its slug via the entity registry.

    For scripts, the entity registry's ``unique_id`` equals the YAML slug under
    ``script:``. When the entity_id is customized away from the default, the
    slug diverges from ``entity_id.removeprefix('script.')``; this bridges it.
    """
    result: dict = {}

    async def handler(send):
        msg = await send({"type": "config/entity_registry/get", "entity_id": entity_id})
        result.update(msg)

    run_ws(handler)
    if result.get("success"):
        return result.get("result", {}).get("unique_id")
    return None


@cli.command("script")
@click.argument("identifier")
def script_cmd(identifier: str) -> None:
    """Fetch script config by entity_id or slug."""
    candidates = [identifier.removeprefix("script.")]
    if identifier.startswith("script."):
        resolved = _resolve_script_slug(identifier)
        if resolved and resolved not in candidates:
            candidates.append(resolved)

    with get_client() as client:
        for slug in candidates:
            try:
                resp = client.request(f"config/script/config/{slug}")
                print_json(resp)
                return
            except EndpointNotFoundError:
                continue
    die(f"Script config not found for {identifier} (tried: {', '.join(candidates)})")
