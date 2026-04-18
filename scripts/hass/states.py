"""List entity states."""

from __future__ import annotations

import click
from homeassistant_api.errors import EndpointNotFoundError

from hass._client import DEFAULT_LIMIT, die, get_client, print_json


@click.command()
@click.argument("targets", nargs=-1)
@click.option("-n", "limit", type=int, help=f"Limit results (default: {DEFAULT_LIMIT})")
@click.option("--all", "no_limit", is_flag=True, help="No limit")
def cli(targets: tuple[str, ...], limit: int | None, no_limit: bool) -> None:
    """List entities. No args: domain summary. One domain: list. Entity IDs: details."""
    with get_client() as client:
        entity_targets = [t for t in targets if "." in t]
        # All targets are entity_ids -> return per-entity details
        if entity_targets and len(entity_targets) == len(targets):
            results = []
            for t in entity_targets:
                try:
                    state = client.get_state(entity_id=t)
                except EndpointNotFoundError:
                    die(f"Entity not found: {t}")
                results.append(state.model_dump())
            print_json(results[0] if len(results) == 1 else results)
            return

        if len(targets) > 1:
            die("Error: mixing domain filter with entity_ids is not supported")

        states = client.get_states()
        if targets:
            domain = targets[0]
            filtered = [
                {
                    "entity_id": s.entity_id,
                    "state": s.state,
                    "name": s.attributes.get("friendly_name", ""),
                }
                for s in states
                if s.entity_id.startswith(f"{domain}.")
            ]
            cap = None if no_limit else (limit or DEFAULT_LIMIT)
            if cap:
                filtered = filtered[:cap]
            print_json(filtered)
            return

        # No args: domain summary
        domains: dict[str, int] = {}
        for s in states:
            d = s.entity_id.split(".")[0]
            domains[d] = domains.get(d, 0) + 1
        print_json(
            sorted(
                [{"domain": d, "count": c} for d, c in domains.items()],
                key=lambda x: -x["count"],
            )
        )
