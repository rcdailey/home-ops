"""Call any API endpoint."""

from __future__ import annotations

import json

import click

from opensprinkler._client import ApiError, call, die


@click.command()
@click.argument("endpoint")
@click.argument("params", nargs=-1)
def cli(endpoint: str, params: tuple[str, ...]) -> None:
    """Call ENDPOINT (e.g. jc, jn, cv) with KEY=VALUE PARAMS; prints the JSON response.

    The password is added automatically. Endpoints and parameters follow the
    firmware API reference (opensprinkler.github.io/OpenSprinkler-Firmware).
    """
    fields = {}
    for p in params:
        key, sep, value = p.partition("=")
        if not sep:
            die(f"bad param {p!r}; use KEY=VALUE")
        fields[key] = value
    try:
        click.echo(json.dumps(call(endpoint, fields), indent=2))
    except ApiError as exc:
        die(str(exc))
