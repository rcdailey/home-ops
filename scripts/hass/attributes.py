"""Show entity attributes."""

from __future__ import annotations

import click
from homeassistant_api.errors import EndpointNotFoundError

from hass._client import die, get_client, print_json


@click.command()
@click.argument("entity_id")
def cli(entity_id: str) -> None:
    """Show attributes (no state) for an entity."""
    with get_client() as client:
        try:
            state = client.get_state(entity_id=entity_id)
        except EndpointNotFoundError:
            die(f"Entity not found: {entity_id}")
    print_json(dict(state.attributes))
