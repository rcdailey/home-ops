"""Display helpers for VictoriaMetrics query output."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import click

# Collector and SDK identity labels that never distinguish workloads
_NOISE_LABELS = frozenset(
    {
        "__name__",
        "k8s_cluster_name",
        "otel_scope_name",
        "otel_scope_version",
        "prometheus",
        "scope_name",
        "scope_version",
        "service_instance_id",
        "telemetry_sdk_language",
        "telemetry_sdk_name",
        "telemetry_sdk_version",
    }
)
# Drop the first label when the second carries the same identity
_REDUNDANT_LABEL_PAIRS = {"instance": "nodename", "host_name": "k8s_node_name"}


def _interesting(metric: dict[str, str]) -> dict[str, str]:
    kept = {k: v for k, v in metric.items() if k not in _NOISE_LABELS}
    for drop_key, keep_key in _REDUNDANT_LABEL_PAIRS.items():
        if drop_key in kept and keep_key in kept:
            del kept[drop_key]
    return kept


def _join(labels: dict[str, str]) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(labels.items()))


def split_labels(results: list[dict]) -> tuple[dict[str, str], list[str]]:
    """Separate labels shared by every series from those that tell series apart.

    Printing the shared labels once keeps OTel resource labels from repeating
    on every row while still showing which pod, node, or service a value
    belongs to.
    """
    metrics = [_interesting(r.get("metric", {})) for r in results]
    if not metrics:
        return {}, []
    common = {
        k: v for k, v in metrics[0].items() if all(m.get(k) == v for m in metrics[1:])
    }
    if len(metrics) == 1:
        return common, [""]
    varying = [{k: v for k, v in m.items() if k not in common} for m in metrics]
    return common, [_join(labels) for labels in varying]


def print_series(results: list[dict], result_type: str) -> None:
    common, labels = split_labels(results)
    if common:
        click.echo(f"common: {_join(common)}")
    click.echo()
    if result_type == "matrix":
        _print_matrix(results, labels)
        return
    for r, label in zip(results, labels, strict=True):
        value = r.get("value", [None, "N/A"])
        click.echo(f"{{{label}}} => {format_value(value[1])}")


def format_value(val: str) -> str:
    try:
        f = float(val)
    except (ValueError, TypeError):
        return val
    if math.isnan(f):
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


def _print_matrix(results: list[dict], series_labels: list[str]) -> None:
    if not results:
        return

    max_points = 50
    # Series start and stop independently (restarts, new pods), so the columns
    # are the union of every series' timestamps, not the first series' points.
    all_timestamps = sorted(
        {float(ts) for r in results for ts, _ in r.get("values", [])}
    )
    if not all_timestamps:
        return
    timestamps = all_timestamps[:max_points]

    moments = [datetime.fromtimestamp(ts, tz=UTC).astimezone() for ts in timestamps]
    dates = sorted({m.strftime("%Y-%m-%d") for m in moments})
    time_fmt = "%m-%d %H:%M" if len(dates) > 1 else "%H:%M:%S"
    time_headers = [m.strftime(time_fmt) for m in moments]
    date_header = dates[0] if len(dates) == 1 else f"{dates[0]} to {dates[-1]}"

    col_width = 8
    for r in results:
        for _, val in r.get("values", [])[:max_points]:
            col_width = max(col_width, len(format_value(val)))
    col_width += 1

    label_width = max((len(lb) for lb in series_labels), default=5)
    label_width = max(label_width, 5)

    click.echo(f"Date: {date_header} ({moments[0].strftime('%Z')})")
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

    total_points = len(all_timestamps)
    if total_points > max_points:
        click.echo(f"... ({total_points} total points, showing first {max_points})")
