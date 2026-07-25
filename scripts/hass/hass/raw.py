"""Direct REST API call for endpoints without a dedicated subcommand."""

from __future__ import annotations

import json
import sys

import click

from hass._client import rest_call
from hass._errors import HassError, die


@click.command()
@click.argument("method")
@click.argument("path")
@click.argument("body", required=False)
def cli(method: str, path: str, body: str | None) -> None:
    """Call METHOD PATH with optional BODY ('-' reads from stdin).

    Service calls belong in `hass call`; the REST service endpoint hides the
    reason a call failed behind a bare 500.
    """
    if body == "-":
        body = sys.stdin.read()
    try:
        payload = json.loads(body) if body else None
    except json.JSONDecodeError as exc:
        die(f"BODY is not valid JSON: {exc}")

    try:
        resp = rest_call(method, path, payload)
    except HassError as exc:
        die(str(exc))

    if isinstance(resp, str):
        click.echo(resp)
    else:
        click.echo(json.dumps(resp, indent=2, default=str))
