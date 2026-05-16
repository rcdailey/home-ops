"""VictoriaMetrics query CLI: PromQL and container stats."""

from __future__ import annotations

import json

import click

from hops._click import HelpfulGroup
from hops.core.format import human_bytes, info, kv
from hops.core.time import TimeRange, time_options
from hops.query._vm import query_vm
from hops.query.metrics_render import (
    _print_matrix,
    compact_labels,
    format_cpu,
    format_value,
)


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


# --- Click commands ---


@click.group(cls=HelpfulGroup)
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
        click.echo(json.dumps(data, indent=2))
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
    click.echo()

    max_series = 20
    if result_type == "matrix":
        _print_matrix(results[:max_series])
    else:
        for r in results[:max_series]:
            metric = r.get("metric", {})
            labels = compact_labels(metric)
            value = r.get("value", [None, "N/A"])
            click.echo(f"{{{labels}}} => {format_value(value[1])}")

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
        click.echo(json.dumps(values, indent=2))
        return

    info(f"{title} ({len(values)} total)")
    for v in values:
        click.echo(v)


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
        click.echo(json.dumps(values, indent=2))
        return

    title = f"Metrics matching '{pattern}'" if pattern else "All metrics"
    info(f"{title} ({len(values)} total)")
    for v in values:
        click.echo(v)
