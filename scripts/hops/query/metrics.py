"""VictoriaMetrics query CLI: PromQL and container stats."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import click

from hops._format import human_bytes, info, kv
from hops._time import TimeRange, time_options
from hops.query._vm import query_vm

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


# --- Formatting helpers ---


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


# --- Container stats helper ---


def container_stats(
    namespace: str,
    pod: str,
    container: str,
    time_range: TimeRange,
    metric: str,
    rate: str | None = None,
) -> dict[str, float | None]:
    duration = time_range.to_duration()
    selector = f'namespace="{namespace}",pod=~"{pod}",container="{container}"'
    base = f"{metric}{{{selector}}}"
    expr = f"rate({base}[{rate}])" if rate else base

    stats: dict[str, float | None] = {"current": None, "max": None, "avg": None}

    data = query_vm("/api/v1/query", {"query": expr})
    results = data.get("data", {}).get("result", [])
    if results:
        stats["current"] = float(results[0]["value"][1])

    data = query_vm("/api/v1/query", {"query": f"max_over_time({expr}[{duration}:])"})
    results = data.get("data", {}).get("result", [])
    if results:
        stats["max"] = max(float(r["value"][1]) for r in results)

    data = query_vm("/api/v1/query", {"query": f"avg_over_time({expr}[{duration}:])"})
    results = data.get("data", {}).get("result", [])
    if results:
        stats["avg"] = sum(float(r["value"][1]) for r in results) / len(results)

    return stats


# --- Matrix printer ---


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

    print(f"Date: {date_header}")
    header = " " * label_width + " | "
    header += " ".join(h.rjust(col_width) for h in time_headers)
    print(header)
    print("-" * len(header))

    for i, r in enumerate(results):
        values = r.get("values", [])
        val_map = {float(ts): val for ts, val in values[:max_points]}
        row = series_labels[i].ljust(label_width) + " | "
        row += " ".join(
            format_value(val_map.get(ts, "")).rjust(col_width) for ts in timestamps
        )
        print(row)

    total_points = len(results[0].get("values", []))
    if total_points > max_points:
        print(f"... ({total_points} total points, showing first {max_points})")


# --- Click commands ---


@click.group()
def cli():
    """Query VictoriaMetrics: PromQL and container stats."""


@cli.command()
@click.argument("namespace")
@click.argument("pod", metavar="POD_REGEX")
@click.argument("container")
@time_options(default_from="7d")
def cpu(
    namespace: str, pod: str, container: str, time_from: str, time_to: str | None, **_
):
    """CPU usage and throttling for a container."""
    time_range = TimeRange.from_options(time_from, time_to)
    duration = time_range.to_duration()

    stats = container_stats(
        namespace,
        pod,
        container,
        time_range,
        "container_cpu_usage_seconds_total",
        rate="5m",
    )

    selector = f'namespace="{namespace}",pod=~"{pod}",container="{container}"'
    throttle_query = (
        f"(sum(increase(container_cpu_cfs_throttled_periods_total{{{selector}}}[{duration}]))"
        f" / sum(increase(container_cpu_cfs_periods_total{{{selector}}}[{duration}]))) * 100"
    )
    throttle_data = query_vm("/api/v1/query", {"query": throttle_query})
    throttle_results = throttle_data.get("data", {}).get("result", [])
    throttle_pct = float(throttle_results[0]["value"][1]) if throttle_results else None

    pairs = []
    if stats["current"] is not None:
        pairs.append(("Current (5m rate)", f"{format_cpu(stats['current'])} cores"))
    else:
        pairs.append(("Current", "No data"))
    if stats["max"] is not None:
        pairs.append((f"Max ({duration})", f"{format_cpu(stats['max'])} cores"))
    if stats["avg"] is not None:
        pairs.append((f"Avg ({duration})", f"{format_cpu(stats['avg'])} cores"))
    if throttle_pct is not None:
        flag = " (!)" if throttle_pct > 25 else ""
        pairs.append((f"Throttled ({duration})", f"{throttle_pct:.2f}%{flag}"))
    kv(pairs)


@cli.command()
@click.argument("namespace")
@click.argument("pod", metavar="POD_REGEX")
@click.argument("container")
@time_options(default_from="7d")
def memory(
    namespace: str, pod: str, container: str, time_from: str, time_to: str | None, **_
):
    """Memory usage for a container."""
    time_range = TimeRange.from_options(time_from, time_to)
    duration = time_range.to_duration()

    stats = container_stats(
        namespace, pod, container, time_range, "container_memory_working_set_bytes"
    )

    pairs = []
    if stats["current"] is not None:
        pairs.append(("Current", human_bytes(stats["current"])))
    else:
        pairs.append(("Current", "No data"))
    if stats["max"] is not None:
        pairs.append((f"Max ({duration})", human_bytes(stats["max"])))
    if stats["avg"] is not None:
        pairs.append((f"Avg ({duration})", human_bytes(stats["avg"])))
    kv(pairs)


@cli.command("query")
@click.argument("promql")
@click.option("--step", default="1m", help="Step interval for range queries")
@click.option("--hide-zero", is_flag=True, help="Hide all-zero series")
@click.option("--json", "json_mode", is_flag=True, help="Output raw JSON")
@time_options(support_at=True)
def raw_query(
    promql: str,
    step: str,
    hide_zero: bool,
    json_mode: bool,
    time_from: str | None,
    time_to: str | None,
    time_at: str | None = None,
    window: str = "10m",
):
    """Execute a raw PromQL query."""
    time_range = TimeRange.from_options(time_from, time_to, time_at, window)

    if time_range.is_current():
        data = query_vm("/api/v1/query", {"query": promql})
    else:
        params = {"query": promql, **time_range.to_range_params(step)}
        data = query_vm("/api/v1/query_range", params)

    if json_mode:
        print(json.dumps(data, indent=2))
        return

    results = data.get("data", {}).get("result", [])
    result_type = data.get("data", {}).get("resultType", "unknown")

    if not results:
        info("No results")
        return

    suffix = ""
    if hide_zero and result_type == "matrix":
        original_count = len(results)
        results = [
            r for r in results if any(float(val) != 0 for _, val in r.get("values", []))
        ]
        hidden = original_count - len(results)
        suffix = f" ({hidden} all-zero hidden)" if hidden else ""
        if not results:
            info(f"No results (all {original_count} series were zero)")
            return

    info(f"{result_type}, {len(results)} series{suffix}")
    print()

    max_series = 20
    if result_type == "matrix":
        _print_matrix(results[:max_series])
    else:
        for r in results[:max_series]:
            metric = r.get("metric", {})
            labels = compact_labels(metric)
            value = r.get("value", [None, "N/A"])
            print(f"{{{labels}}} => {format_value(value[1])}")

    if len(results) > max_series:
        info(f"... {len(results) - max_series} more series")


@cli.command()
@click.argument("name", required=False)
@click.option("--json", "json_mode", is_flag=True, help="Output raw JSON")
def labels(name: str | None, json_mode: bool):
    """List label names or values for a specific label."""
    if name:
        data = query_vm(f"/api/v1/label/{name}/values")
        title = f"Values for '{name}'"
    else:
        data = query_vm("/api/v1/labels")
        title = "All labels"

    values = data.get("data", [])

    if json_mode:
        print(json.dumps(values, indent=2))
        return

    info(f"{title} ({len(values)} total)")
    for v in values:
        print(v)


@cli.command("metrics")
@click.option(
    "-f", "--filter", "pattern", default=None, help="Filter pattern (case-insensitive)"
)
@click.option("--json", "json_mode", is_flag=True, help="Output raw JSON")
def list_metrics(pattern: str | None, json_mode: bool):
    """List metric names with optional filter."""
    data = query_vm("/api/v1/label/__name__/values")
    values = data.get("data", [])
    if pattern:
        p = pattern.lower()
        values = [v for v in values if p in v.lower()]

    if json_mode:
        print(json.dumps(values, indent=2))
        return

    title = f"Metrics matching '{pattern}'" if pattern else "All metrics"
    info(f"{title} ({len(values)} total)")
    for v in values:
        print(v)
