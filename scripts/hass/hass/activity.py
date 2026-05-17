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

    # Include date in the timestamp when the window spans more than ~1 day,
    # otherwise bare HH:MM:SS is ambiguous across day boundaries.
    show_date = hours > 24
    for e in entries:
        d = e.model_dump() if hasattr(e, "model_dump") else vars(e)
        ts = str(d.get("when", ""))
        # when is ISO-8601; split date and time halves
        date_part, time_part = "", ts
        if "T" in ts:
            date_part, _, time_part = ts.partition("T")
        elif " " in ts:
            date_part, _, time_part = ts.partition(" ")
        time_part = time_part[:8]
        ts = f"{date_part} {time_part}" if show_date and date_part else time_part
        name = d.get("name", d.get("entity_id", ""))
        state = d.get("state", "")
        message = d.get("message", "")
        parts = [ts, name]
        if state:
            parts.append(f"-> {state}")
        if message:
            parts.append(f"({message})")
        click.echo("  ".join(parts))
