"""Direct WebSocket command for operations without a dedicated subcommand."""

from __future__ import annotations

import json
import sys

import click

from hass._client import print_json, run_ws, ws_error
from hass._errors import die


@click.command()
@click.argument("msg_type")
@click.argument("body", required=False)
def cli(msg_type: str, body: str | None) -> None:
    """Send WebSocket command MSG_TYPE with optional JSON BODY fields ('-' reads stdin).

    Covers registry and storage operations the REST API lacks, e.g.
    `hass ws config/label_registry/delete '{"label_id": "exterior"}'`.
    Prints the result; exits non-zero with HA's error message on failure.
    """
    if body == "-":
        body = sys.stdin.read()
    try:
        fields = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        die(f"BODY is not valid JSON: {exc}")
    if not isinstance(fields, dict):
        die("BODY must be a JSON object")

    async def handler(send):
        msg = await send({**fields, "type": msg_type})
        if not msg.get("success"):
            die(ws_error(msg))
        print_json(msg.get("result"))

    run_ws(handler)
