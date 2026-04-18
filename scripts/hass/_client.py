"""Shared HA client, environment, and WebSocket plumbing."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

import click
from homeassistant_api import Client

DEFAULT_LIMIT = 20


def die(msg: str, code: int = 1) -> None:
    """Print an error to stderr and exit."""
    click.echo(msg, err=True)
    sys.exit(code)


def _env() -> tuple[str, str]:
    domain = os.environ.get("SECRET_DOMAIN")
    token = os.environ.get("HASS_TOKEN")
    if not domain:
        die("Error: SECRET_DOMAIN is not set")
    if not token:
        die("Error: HASS_TOKEN is not set")
    return domain, token  # type: ignore[return-value]


def get_client() -> Client:
    domain, token = _env()
    return Client(f"https://ha.{domain}/api", token)


def ws_error(msg: dict) -> str:
    """Extract error message from a failed WebSocket response."""
    return msg.get("error", {}).get("message", json.dumps(msg))


def parse_time_arg(value: str, now: datetime) -> datetime:
    """Parse a time argument as hours-ago (number/Nh) or ISO timestamp."""
    try:
        hours = float(value.rstrip("h"))
        return now - timedelta(hours=hours)
    except ValueError:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


WsHandler = Callable[[Callable[[dict], Awaitable[dict]]], Awaitable]


async def _ws_call(handler: WsHandler):
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


def run_ws(handler: WsHandler):
    """Synchronous entry point for a WebSocket handler."""
    return asyncio.run(_ws_call(handler))


def print_json(obj) -> None:
    """Pretty-print JSON with datetime fallback."""
    click.echo(json.dumps(obj, indent=2, default=str))
