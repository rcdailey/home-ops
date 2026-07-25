"""Invoke arbitrary Home Assistant service actions.

Calls go over the WebSocket API rather than ``POST /api/services/...``: the REST
endpoint collapses every failure into an opaque 500 ("Server got itself in
trouble"), while the WebSocket result carries Home Assistant's own error.
"""

from __future__ import annotations

from typing import Any

import click
import yaml

from hass._client import Send, print_json, run_ws, ws_error
from hass._errors import HassError, die


async def call_service(
    send: Send,
    domain: str,
    service: str,
    entities: list[str] | None = None,
    data: dict | None = None,
    return_response: bool = False,
) -> dict:
    """Call ``domain.service``, raising ``HassError`` with HA's own message."""
    payload: dict[str, Any] = {
        "type": "call_service",
        "domain": domain,
        "service": service,
        "service_data": data or {},
    }
    if entities:
        payload["target"] = {"entity_id": entities}
    if return_response:
        payload["return_response"] = True
    msg = await send(payload)
    if not msg.get("success"):
        raise HassError(ws_error(msg))
    return msg.get("result") or {}


def parse_data(raw: str | None) -> dict:
    """Parse service data given as YAML or JSON ('-' reads stdin)."""
    if not raw:
        return {}
    text = click.get_text_stream("stdin").read() if raw == "-" else raw
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise HassError(f"--data is not valid YAML/JSON: {exc}") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise HassError("--data must be a mapping of service fields")
    return data


@click.command()
@click.argument("service")
@click.argument("entities", nargs=-1)
@click.option("--data", "raw_data", help="Service fields as YAML/JSON ('-' for stdin)")
@click.option("--response", is_flag=True, help="Request the service response data")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def cli(
    service: str,
    entities: tuple[str, ...],
    raw_data: str | None,
    response: bool,
    as_json: bool,
) -> None:
    """Call SERVICE (domain.service) against optional target ENTITIES.

    \b
    Examples:
      hass call media_player.volume_set media_player.wiim_patio --data 'volume_level: 0.2'
      hass call light.turn_on light.office --data 'brightness_pct: 40'
      hass call weather.get_forecasts weather.home --data 'type: daily' --response
    """
    if "." not in service:
        die(f"service must be domain.service: {service}")
    domain, name = service.split(".", 1)
    try:
        data = parse_data(raw_data)
    except HassError as exc:
        die(str(exc))

    async def handler(send):
        result = await call_service(send, domain, name, list(entities), data, response)
        if as_json:
            print_json(result)
            return
        target = " on " + ", ".join(entities) if entities else ""
        click.echo(f"called {service}{target}")
        if response and result.get("response") is not None:
            print_json(result["response"])

    try:
        run_ws(handler)
    except HassError as exc:
        die(str(exc))
