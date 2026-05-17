"""Direct REST API call for endpoints without a dedicated subcommand."""

from __future__ import annotations

import json
import sys

import click

from hass._client import get_client


@click.command()
@click.argument("method")
@click.argument("path")
@click.argument("body", required=False)
def cli(method: str, path: str, body: str | None) -> None:
    """Call METHOD PATH with optional BODY ('-' reads from stdin)."""
    if body == "-":
        body = sys.stdin.read()

    with get_client() as client:
        api_path = path.removeprefix("/api/")
        kwargs: dict = {}
        if body:
            kwargs["json"] = json.loads(body)
        m = method.upper()
        if m == "GET":
            resp = client.request(api_path)
        else:
            resp = client.request(api_path, method=m, **kwargs)

    if isinstance(resp, str):
        click.echo(resp)
    else:
        click.echo(json.dumps(resp, indent=2, default=str))
