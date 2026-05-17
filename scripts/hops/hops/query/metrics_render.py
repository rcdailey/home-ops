"""Display helpers for VictoriaMetrics query output."""

from __future__ import annotations

from datetime import datetime, timezone

import click

# Labels that are always noise in investigation output
_NOISE_LABELS = frozenset(
    {
        "__name__",
        "container",
        "endpoint",
        "job",
        "namespace",
        "pod",
        "prometheus",
        "service",
    }
)
_REDUNDANT_LABEL_PAIRS = {"instance": "nodename"}


def compact_labels(metric: dict[str, str]) -> str:
    interesting = {k: v for k, v in metric.items() if k not in _NOISE_LABELS}
    for drop_key, keep_key in _REDUNDANT_LABEL_PAIRS.items():
        if drop_key in interesting and keep_key in interesting:
            del interesting[drop_key]
    if not interesting:
        interesting = {k: v for k, v in metric.items() if k != "__name__"}
    if len(interesting) == 1:
        return next(iter(interesting.values()))
    return ", ".join(f"{k}={v}" for k, v in interesting.items())


def format_value(val: str) -> str:
    try:
        f = float(val)
    except (ValueError, TypeError):
        return val
    if f != f:
        return "NaN"
    if abs(f) == float("inf"):
        return val
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    abs_f = abs(f)
    if abs_f >= 100:
        return f"{f:.1f}"
    if abs_f >= 1:
        return f"{f:.3f}"
    if abs_f >= 0.001:
        return f"{f:.4f}"
    return f"{f:.6f}"


def format_cpu(value: float) -> str:
    if value < 0.001:
        return f"{value * 1000000:.0f}u"
    elif value < 1:
        return f"{value * 1000:.0f}m"
    return f"{value:.2f}"


def _print_matrix(results: list[dict]) -> None:
    if not results:
        return

    max_points = 50
    all_values = results[0].get("values", [])
    if not all_values:
        return

    timestamps = [float(ts) for ts, _ in all_values[:max_points]]
    if not timestamps:
        return

    prev_date = ""
    time_headers: list[str] = []
    date_header = ""
    for ts in timestamps:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M:%S")
        if date_str != prev_date:
            date_header = date_str
            prev_date = date_str
        time_headers.append(time_str)

    series_labels = [compact_labels(r.get("metric", {})) for r in results]
    col_width = 8
    for r in results:
        for _, val in r.get("values", [])[:max_points]:
            col_width = max(col_width, len(format_value(val)))
    col_width += 1

    label_width = max((len(lb) for lb in series_labels), default=5)
    label_width = max(label_width, 5)

    click.echo(f"Date: {date_header}")
    header = " " * label_width + " | "
    header += " ".join(h.rjust(col_width) for h in time_headers)
    click.echo(header)
    click.echo("-" * len(header))

    for i, r in enumerate(results):
        values = r.get("values", [])
        val_map = {float(ts): val for ts, val in values[:max_points]}
        row = series_labels[i].ljust(label_width) + " | "
        row += " ".join(
            format_value(val_map.get(ts, "")).rjust(col_width) for ts in timestamps
        )
        click.echo(row)

    total_points = len(results[0].get("values", []))
    if total_points > max_points:
        click.echo(f"... ({total_points} total points, showing first {max_points})")
