"""Entity logbook timeline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import click

from hass._client import get_client


@click.command()
@click.argument("entities", nargs=-1, required=True)
@click.option("--hours", type=float, default=1, help="Lookback hours (default: 1)")
def cli(entities: tuple[str, ...], hours: float) -> None:
    """Show timestamped state changes from the HA logbook."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    with get_client() as client:
        entries = list(
            client.get_logbook_entries(
                filter_entities=list(entities),
                start_timestamp=since,
            )
        )

    if not entries:
        click.echo("(no activity found)")
        return

    for e in entries:
        d = e.model_dump() if hasattr(e, "model_dump") else vars(e)
        ts = str(d.get("when", ""))
        if "T" in ts:
            ts = ts.split("T")[1][:8]
        elif " " in ts:
            ts = ts.split(" ")[1][:8]
        name = d.get("name", d.get("entity_id", ""))
        state = d.get("state", "")
        message = d.get("message", "")
        parts = [ts, name]
        if state:
            parts.append(f"-> {state}")
        if message:
            parts.append(f"({message})")
        click.echo("  ".join(parts))
