"""Long-term statistics from the recorder, as a period-by-entity table."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

import click

from hass._client import parse_time_arg, print_json, run_ws, ws_error
from hass._errors import die

# Recorder converts these unit classes server-side, so Wh and kWh sensors share one scale.
UNITS = {"energy": "kWh", "power": "W"}
TYPES = ("change", "mean", "min", "max", "state", "sum")
AUTO = "auto"


def _fetch(
    entities: tuple[str, ...], start: datetime, end: datetime, period: str
) -> tuple[dict, dict]:
    result: dict = {}

    async def handler(send):
        stats = await send(
            {
                "type": "recorder/statistics_during_period",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "statistic_ids": list(entities),
                "period": period,
                "types": list(TYPES),
                "units": UNITS,
            }
        )
        if not stats.get("success"):
            die(f"Error: {ws_error(stats)}")
        meta = await send(
            {
                "type": "recorder/get_statistics_metadata",
                "statistic_ids": list(entities),
            }
        )
        if not meta.get("success"):
            die(f"Error: {ws_error(meta)}")
        result["stats"] = stats["result"]
        result["meta"] = {m["statistic_id"]: m for m in meta["result"]}

    run_ws(handler)
    return result["stats"], result["meta"]


def _stat_type(rows: list[dict], requested: str) -> str:
    """Pick ``change`` for cumulative meters and ``mean`` for measurements."""
    if requested != AUTO:
        return requested
    if any(r.get("change") is not None for r in rows):
        return "change"
    return "mean"


def _unit(meta: dict) -> str:
    unit = meta.get("statistics_unit_of_measurement") or ""
    return UNITS.get(meta.get("unit_class") or "", unit)


def _bucket_label(start_ms: int, period: str, profile: bool) -> str:
    local = datetime.fromtimestamp(start_ms / 1000, UTC).astimezone()
    if profile:
        return local.strftime("%H:00")
    fmt = {"5minute": "%m-%d %H:%M", "hour": "%m-%d %H:00", "month": "%Y-%m"}
    return local.strftime(fmt.get(period, "%Y-%m-%d"))


def _fmt(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}" if abs(value) < 100 else f"{value:.0f}"


@click.command()
@click.argument("entities", nargs=-1, required=True)
@click.option(
    "--from",
    "start",
    default="168",
    help="Start: hours ago (e.g., 24, 720h) or ISO timestamp (default: 7 days)",
)
@click.option("--to", "end", default=None, help="End: hours ago or ISO timestamp")
@click.option(
    "--period",
    type=click.Choice(["5minute", "hour", "day", "week", "month"]),
    default="day",
    show_default=True,
)
@click.option(
    "--type",
    "stat_type",
    type=click.Choice((AUTO, *TYPES)),
    default=AUTO,
    show_default=True,
    help="Statistic to show; auto uses change for meters and mean for measurements",
)
@click.option(
    "--profile",
    is_flag=True,
    help="Average buckets by local hour of day (use with --period hour)",
)
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def cli(
    entities: tuple[str, ...],
    start: str,
    end: str | None,
    period: str,
    stat_type: str,
    profile: bool,
    as_json: bool,
) -> None:
    """Show long-term statistics for ENTITIES, one column per entity.

    Statistics are hourly and longer aggregates the recorder keeps after raw history is
    purged, so they reach back further than `history`. Energy values are converted to
    kWh and power to W. The footer totals `change` columns and averages the rest.
    """
    if profile and period != "hour":
        die("--profile requires --period hour")
    now = datetime.now(UTC)
    start_ts = parse_time_arg(start, now)
    end_ts = parse_time_arg(end, now) if end else now
    stats, meta = _fetch(entities, start_ts, end_ts, period)

    if as_json:
        print_json({"metadata": meta, "statistics": stats})
        return

    missing = [e for e in entities if e not in meta]
    if missing:
        die(f"No long-term statistics for: {', '.join(missing)}")

    columns: list[tuple[str, str]] = []
    table: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for entity in entities:
        rows = stats.get(entity, [])
        kind = _stat_type(rows, stat_type)
        columns.append((entity, kind))
        for row in rows:
            value = row.get(kind)
            if value is None:
                continue
            label = _bucket_label(row["start"], period, profile)
            table[label][entity].append(value)

    if not table:
        click.echo("(no statistics in range)")
        return

    def cell(label: str, entity: str) -> float | None:
        values = table[label].get(entity)
        return sum(values) / len(values) if values else None

    headers = ["period"] + [
        f"{e.removeprefix('sensor.')} ({k}, {_unit(meta[e])})" for e, k in columns
    ]
    lines = [
        [label] + [_fmt(cell(label, e)) for e, _ in columns] for label in sorted(table)
    ]
    footer = ["total/avg"]
    for entity, kind in columns:
        values = [v for label in table if (v := cell(label, entity)) is not None]
        if not values:
            footer.append("-")
            continue
        aggregate = (
            sum(values)
            if kind == "change" and not profile
            else sum(values) / len(values)
        )
        footer.append(_fmt(aggregate))
    lines.append(footer)

    click.echo("\n".join("\t".join(row) for row in [headers, *lines]))
