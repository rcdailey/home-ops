"""Entity state history with numeric and categorical summaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import quote

import click

from hass._client import get_client, parse_time_arg
from hass._errors import die
from hass._format import is_numeric, print_history_entry


def _timestamp(entry: dict) -> datetime:
    return datetime.fromisoformat(entry["last_changed"])


def _attribute_series(series: list[dict], attribute: str) -> list[dict]:
    """Project full history entries onto one attribute, dropping unchanged repeats.

    Attribute-only changes move ``last_updated`` but not ``last_changed``, so the
    projected entry carries ``last_updated`` as its change time.
    """
    entity_id = series[0].get("entity_id", "unknown")
    if not any(attribute in entry.get("attributes", {}) for entry in series):
        die(f"{entity_id} has no attribute {attribute!r} in this range")
    projected: list[dict] = []
    for entry in series:
        value = str(entry.get("attributes", {}).get(attribute))
        if projected and projected[-1]["state"] == value:
            continue
        changed = entry.get("last_updated") or entry["last_changed"]
        projected.append(
            {"entity_id": entity_id, "state": value, "last_changed": changed}
        )
    return projected


@click.command()
@click.argument("entities", nargs=-1, required=True)
@click.option(
    "--from",
    "start",
    default="24",
    help="Start: hours ago (e.g., 24, 1h) or ISO timestamp (default: 24h)",
)
@click.option(
    "--to",
    "end",
    default=None,
    help="End: hours ago or ISO timestamp (default: now)",
)
@click.option(
    "-n", "limit", type=int, help="Head/tail entries per entity (default: 10)"
)
@click.option(
    "--summary",
    is_flag=True,
    help="Summarize: numeric -> min/max/first/last/resets; categorical -> counts + transitions",
)
@click.option(
    "--attribute",
    help="Track this attribute instead of the state (e.g. hvac_action, fan_mode)",
)
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def cli(
    entities: tuple[str, ...],
    start: str,
    end: str | None,
    limit: int | None,
    summary: bool,
    attribute: str | None,
    as_json: bool,
) -> None:
    """Fetch state history and summarize it.

    Categorical summaries report how long each value was held, so `--summary
    --attribute hvac_action` on a climate entity gives heating, cooling, and fan runtime.
    """
    now = datetime.now(UTC)
    start_ts = parse_time_arg(start, now)
    end_ts = parse_time_arg(end, now) if end else now

    entity_filter = ",".join(entities)
    path = (
        f"history/period/{quote(start_ts.isoformat())}"
        f"?filter_entity_id={quote(entity_filter)}"
        f"&end_time={quote(end_ts.isoformat())}"
    )
    if not attribute:
        path += "&minimal_response&no_attributes"

    with get_client() as client:
        data = client.request(path)

    if not data:
        click.echo("(no history)")
        return

    for series in data:
        if not series:
            continue
        if attribute:
            series = _attribute_series(series, attribute)

        entity_id = series[0].get("entity_id", "unknown")
        numeric = all(
            is_numeric(e.get("state", ""))
            for e in series
            if e.get("state") not in ("unavailable", "unknown")
        )

        if as_json:
            click.echo(json.dumps({"entity_id": entity_id, "states": series}, indent=2))
            continue

        click.echo(f"--- {entity_id} ({len(series)} points) ---")

        if summary and numeric:
            values = [
                float(e["state"]) for e in series if is_numeric(e.get("state", ""))
            ]
            if values:
                resets = sum(
                    1 for i in range(1, len(values)) if values[i] < values[i - 1] * 0.5
                )
                click.echo(
                    f"  range:  {series[0]['last_changed']}  ->  "
                    f"{series[-1]['last_changed']}"
                )
                click.echo(f"  first:  {values[0]}")
                click.echo(f"  last:   {values[-1]}")
                click.echo(f"  min:    {min(values)}")
                click.echo(f"  max:    {max(values)}")
                click.echo(f"  points: {len(values)}")
                if resets:
                    click.echo(f"  resets: {resets}")
            continue

        if summary:
            counts: dict[str, int] = {}
            held: dict[str, float] = {}
            transitions: list[tuple[str, str]] = []
            prev_state: str | None = None
            for i, entry in enumerate(series):
                s = entry.get("state", "")
                counts[s] = counts.get(s, 0) + 1
                begin = max(_timestamp(entry), start_ts)
                finish = _timestamp(series[i + 1]) if i + 1 < len(series) else end_ts
                held[s] = held.get(s, 0.0) + max((finish - begin).total_seconds(), 0.0)
                if s != prev_state:
                    transitions.append((entry.get("last_changed", ""), s))
                    prev_state = s
            click.echo(
                f"  range:  {series[0]['last_changed']}  ->  "
                f"{series[-1]['last_changed']}"
            )
            click.echo(
                f"  points: {len(series)}  unique: {len(counts)}  "
                f"transitions: {len(transitions)}"
            )
            window = (end_ts - start_ts).total_seconds()
            click.echo("  time held (points):")
            for value, seconds in sorted(held.items(), key=lambda x: -x[1]):
                click.echo(
                    f"    {value}: {seconds / 3600:.1f}h "
                    f"({seconds / window:.0%})  ({counts[value]})"
                )
            tlimit = limit or 10
            thead = transitions[:tlimit]
            ttail = transitions[-tlimit:] if len(transitions) > tlimit * 2 else []
            skipped = len(transitions) - len(thead) - len(ttail)
            click.echo("  transitions:")
            for ts, s in thead:
                print_history_entry({"last_changed": ts, "state": s})
            if skipped > 0:
                click.echo(f"  ... ({skipped} more)")
            for ts, s in ttail:
                print_history_entry({"last_changed": ts, "state": s})
            continue

        # Default: head/tail
        cap = limit or 10
        head = series[:cap]
        tail = series[-cap:] if len(series) > cap * 2 else []
        skipped = len(series) - len(head) - len(tail)
        for entry in head:
            print_history_entry(entry)
        if skipped > 0:
            click.echo(f"  ... ({skipped} more)")
        for entry in tail:
            print_history_entry(entry)
