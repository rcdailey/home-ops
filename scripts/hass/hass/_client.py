"""Shared HA client, environment, and WebSocket plumbing."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import click
from homeassistant_api import Client

from hass._errors import HassError, die

DEFAULT_LIMIT = 20


def _env() -> tuple[str, str]:
    domain = os.environ.get("SECRET_DOMAIN")
    token = os.environ.get("HASS_TOKEN")
    if not domain:
        die("SECRET_DOMAIN is not set")
    if not token:
        die("HASS_TOKEN is not set")
    return domain, token  # type: ignore[return-value]


def get_client() -> Client:
    """Return an authenticated HA REST client."""
    domain, token = _env()
    return Client(f"https://ha.{domain}/api", token)


_GENERIC_PREFIX = re.compile(r"^(Validation error|Error): ")


def ws_error(msg: dict) -> str:
    """Render a failed WebSocket response as ``Label: Home Assistant's message``.

    HA labels service failures with a ``translation_key`` naming the exception it
    raised (``service_not_supported`` -> ``ServiceNotSupported``); that is more
    useful than the generic ``code`` it pairs with.
    """
    error = msg.get("error")
    if not error:
        return json.dumps(msg)
    text = _GENERIC_PREFIX.sub("", error.get("message") or json.dumps(error))
    key = error.get("translation_key")
    label = "".join(p.title() for p in key.split("_")) if key else error.get("code")
    return f"{label}: {text}" if label else text


def rest_error(status: int, body: str) -> str:
    """Render a failed REST response, unwrapping HA's JSON error envelope."""
    text = " ".join(body.split())
    try:
        parsed = json.loads(text)
        text = parsed.get("message") or text if isinstance(parsed, dict) else text
    except json.JSONDecodeError:
        pass
    hint = (
        " (POST /api/services always reports 500 on failure with no detail; "
        "use `hass call` for the real error)"
        if status >= 500
        else ""
    )
    return f"HTTP {status}: {text}{hint}"


def rest_call(method: str, path: str, payload: Any | None = None) -> Any:
    """Call the REST API directly, surfacing HA's response body on failure.

    ``homeassistant_api`` raises on non-2xx responses with the body buried in a
    "report this upstream" message, so raw calls go through ``requests`` instead.
    """
    import requests

    domain, token = _env()
    url = f"https://ha.{domain}/api/{path.removeprefix('/api/').lstrip('/')}"
    resp = requests.request(
        method.upper(),
        url,
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=60,
    )
    if not resp.ok:
        raise HassError(rest_error(resp.status_code, resp.text))
    if "application/json" in resp.headers.get("content-type", ""):
        return resp.json()
    return resp.text


def rest_get(path: str) -> Any | None:
    """GET a REST path, returning None when the object does not exist."""
    try:
        return rest_call("GET", path)
    except HassError as exc:
        if "404" in str(exc):
            return None
        raise


def parse_time_arg(value: str, now: datetime) -> datetime:
    """Parse a time argument as hours-ago (number/Nh) or ISO timestamp."""
    try:
        hours = float(value.rstrip("h"))
        return now - timedelta(hours=hours)
    except ValueError:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


Send = Callable[[dict], Awaitable[dict]]
WsHandler = Callable[[Send], Awaitable[Any]]


async def _ws_call(handler: WsHandler) -> Any:
    """Run an async handler with an authenticated WebSocket send function.

    The handler receives a single ``send`` coroutine that assigns message IDs
    automatically, sends the payload, and returns the response dict.
    """
    import aiohttp

    domain, token = _env()
    url = f"wss://ha.{domain}/api/websocket"
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url) as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": token})
            msg = await ws.receive_json()
            if msg["type"] != "auth_ok":
                die(json.dumps(msg))

            msg_id = 0

            async def send(payload: dict) -> dict:
                nonlocal msg_id
                msg_id += 1
                payload["id"] = msg_id
                await ws.send_json(payload)
                return await ws.receive_json()

            return await handler(send)


def run_ws(handler: WsHandler) -> Any:
    """Synchronous entry point for a WebSocket handler."""
    return asyncio.run(_ws_call(handler))


def print_json(obj: Any) -> None:
    """Pretty-print JSON with datetime fallback."""
    click.echo(json.dumps(obj, indent=2, default=str))
