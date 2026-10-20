"""Send any Z-Wave JS server command."""

from __future__ import annotations

import json
import sys

import click

from zwave._client import Session, die, print_json, run


@click.command()
@click.argument("command")
@click.argument("body", required=False)
def cli(command: str, body: str | None) -> None:
    """Send COMMAND with optional JSON BODY fields ('-' reads stdin).

    For server commands without a dedicated subcommand, e.g.
    `zwave cmd node.get_value '{"nodeId": 21, "valueId": {"commandClass": 38,
    "property": "currentValue"}}'`. Commands follow the zwave-js-server API.
    """
    if body == "-":
        body = sys.stdin.read()
    try:
        fields = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        die(f"BODY is not valid JSON: {exc}")
    if not isinstance(fields, dict):
        die("BODY must be a JSON object")

    async def handler(session: Session):
        return await session.send(command, **fields)

    print_json(run(handler))
