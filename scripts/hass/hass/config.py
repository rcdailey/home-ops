"""Get automation/script configuration."""

from __future__ import annotations

import click

from hass import _target as tg
from hass._client import print_json
from hass._errors import HassError, die


@click.group()
def cli() -> None:
    """Get automation or script configuration (as JSON).

    Use `hass edit pull`/`push` to change a config; this is read-only.
    """


def _show(kind: str, ref: str) -> None:
    config = tg.Target(kind, ref).fetch()
    if config is None:
        raise HassError(f"no such {kind} {ref}")
    print_json(config)


@cli.command("automation")
@click.argument("identifier")
def automation_cmd(identifier: str) -> None:
    """Fetch automation config by entity_id or UUID."""
    try:
        _show("automation", tg.resolve_automation_id(identifier))
    except HassError as exc:
        die(str(exc))


@cli.command("script")
@click.argument("identifier")
def script_cmd(identifier: str) -> None:
    """Fetch script config by entity_id or slug."""
    try:
        _show("script", tg.resolve_script_slug(identifier))
    except HassError as exc:
        die(str(exc))
