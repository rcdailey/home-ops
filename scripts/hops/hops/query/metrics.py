"""VictoriaMetrics query CLI: PromQL and container stats."""

from __future__ import annotations

import json
from collections.abc import Callable

import click

from hops._click import HelpfulGroup
from hops.core.format import format_timestamp, human_bytes, info, kv, table
from hops.core.runner import run
from hops.core.time import TimeRange, time_options
from hops.core.workload import resolve_pods, select_pods_for_logs, suggest_near_matches
from hops.query import container_usage as cu
from hops.query._vm import query_vm
from hops.query.metrics_diagnose import diagnose_empty
from hops.query.metrics_render import format_cpu, print_series

# --- Container resolution ---


def _resolve_container(
    app: str, namespace: str | None, container: str | None
) -> tuple[str, str, str, list[str]]:
    """Resolve an app to a pod regex covering its history and one container."""
    resolved = resolve_pods(app, namespace)
    if not resolved:
        hints = suggest_near_matches(app, namespace)
        info(f"error: could not find app {app!r}")
        if hints:
            info(f"  similar: {', '.join(hints)}")
        raise SystemExit(1)

    ns, pods = resolved
    chosen = select_pods_for_logs(pods)
    pod_names = [pod.get("metadata", {}).get("name", "") for pod in chosen]
    pod_names = [name for name in pod_names if name]
    containers = sorted(
        {
            item.get("name", "")
            for pod in chosen
            for item in pod.get("spec", {}).get("containers", [])
            if item.get("name")
        }
    )
    if container is None:
        if len(containers) != 1:
            info(f"error: choose a container with -c: {', '.join(containers)}")
            raise SystemExit(1)
        container = containers[0]
    elif container not in containers:
        info(
            f"error: container {container!r} not found; choose: {', '.join(containers)}"
        )
        raise SystemExit(1)

    assert container is not None
    return ns, cu.workload_pod_regex(pods), container, pod_names


def _metrics_server_current(
    namespace: str, pod_names: list[str], container: str, resource: str
) -> float | None:
    """Return current usage when VictoriaMetrics has not scraped the pod yet."""
    result = run(
        [
            "kubectl",
            "top",
            "pods",
            "-n",
            namespace,
            "--no-headers",
            "--containers",
        ],
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        return None

    values = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0] not in pod_names or parts[1] != container:
            continue
        value = parts[2] if resource == "cpu" else parts[3]
        parsed = _parse_cpu(value) if resource == "cpu" else _parse_memory(value)
        if parsed is not None:
            values.append(parsed)
    return max(values) if values else None


def _parse_cpu(value: str) -> float | None:
    """Parse kubectl CPU quantities into cores."""
    try:
        return float(value[:-1]) / 1000 if value.endswith("m") else float(value)
    except ValueError:
        return None


def _parse_memory(value: str) -> float | None:
    """Parse kubectl binary memory quantities into bytes."""
    units = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3}
    for suffix, multiplier in units.items():
        if value.endswith(suffix):
            try:
                return float(value[: -len(suffix)]) * multiplier
            except ValueError:
                return None
    try:
        return float(value)
    except ValueError:
        return None


# --- Click commands ---


@click.group(cls=HelpfulGroup)
def cli():
    """Query VictoriaMetrics: PromQL and container stats."""


@cli.command()
@click.argument("app")
@click.option("-n", "--namespace", help="Namespace (auto-detected if omitted)")
@click.option("-c", "--container", help="Container (inferred when unambiguous)")
@time_options(default_from="7d")
def cpu(
    app: str,
    namespace: str | None,
    container: str | None,
    time_from: str,
    time_to: str | None,
    **_,
):
    """CPU usage over time for a container: current, peak, average, hourly-style buckets."""
    _report_usage(
        app,
        namespace,
        container,
        TimeRange.from_options(time_from, time_to),
        "cpu",
        lambda value: f"{format_cpu(value)} cores",
    )


@cli.command()
@click.argument("app")
@click.option("-n", "--namespace", help="Namespace (auto-detected if omitted)")
@click.option("-c", "--container", help="Container (inferred when unambiguous)")
@time_options(default_from="7d")
def memory(
    app: str,
    namespace: str | None,
    container: str | None,
    time_from: str,
    time_to: str | None,
    **_,
):
    """Memory working set over time for a container: current, peak, average, buckets."""
    _report_usage(
        app,
        namespace,
        container,
        TimeRange.from_options(time_from, time_to),
        "memory",
        human_bytes,
    )


_USAGE_METRICS = {
    "cpu": (cu.CPU_USAGE, cu.CPU_REQUEST, cu.CPU_LIMIT),
    "memory": (cu.MEMORY_WORKING_SET, cu.MEMORY_REQUEST, cu.MEMORY_LIMIT),
}


def _report_usage(
    app: str,
    namespace: str | None,
    container: str | None,
    time_range: TimeRange,
    resource: str,
    fmt: Callable[[float], str],
) -> None:
    ns, pod_regex, container, pod_names = _resolve_container(app, namespace, container)
    metric, request_metric, limit_metric = _USAGE_METRICS[resource]
    result = cu.usage(
        metric,
        request_metric,
        limit_metric,
        cu.selector(ns, pod_regex, container),
        time_range,
    )
    current = result.current
    if current is None:
        current = _metrics_server_current(ns, pod_names, container, resource)

    window = time_range.describe()
    pairs = [("Target", f"{ns}/{container} in pods matching {pod_regex}")]
    if result.buckets:
        window_start = float(time_range.to_epoch_range_params()["start"])
        first = result.buckets[0].start
        if first - window_start > 3600:
            since = format_timestamp(first, local=True)
            pairs.append(("Data since", f"{since} (no samples earlier in window)"))
    pairs.append(("Current", fmt(current) if current is not None else "No data"))
    if result.peak is not None and result.peak_at is not None:
        at = format_timestamp(result.peak_at, local=True)
        pairs.append((f"Peak ({window})", f"{fmt(result.peak)} at {at}"))
    if result.avg is not None:
        pairs.append((f"Avg ({window})", fmt(result.avg)))
    pairs.append(("Request", fmt(result.request) if result.request else "none"))
    limit = fmt(result.limit) if result.limit else "none"
    if result.limit and result.peak is not None:
        limit += f" (peak is {result.peak / result.limit:.0%} of limit)"
    pairs.append(("Limit", limit))
    kv(pairs)

    if not result.buckets:
        info(f"\nNo {metric} samples in {window}")
        return
    click.echo()
    labels = cu.bucket_labels(result.buckets)
    table(
        ["FROM", "PEAK", "AVG"],
        [
            [label, fmt(b.peak), fmt(b.avg)]
            for label, b in zip(labels, result.buckets, strict=True)
        ],
    )


@cli.command("query")
@click.argument("promql")
@click.option(
    "--step", default="auto", help="Step interval for range queries (default: auto)"
)
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
        diagnose_empty(promql)
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
    max_series = 20
    print_series(results[:max_series], result_type)
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
@click.argument("pattern", required=False)
@click.option("--json", "json_mode", is_flag=True, help="Output raw JSON")
def list_metrics(pattern: str | None, json_mode: bool):
    """List metric names containing every space-separated PATTERN term."""
    data = query_vm("/api/v1/label/__name__/values")
    values = data.get("data", [])
    if pattern:
        terms = pattern.lower().split()
        values = [v for v in values if all(term in v.lower() for term in terms)]

    if json_mode:
        click.echo(json.dumps(values, indent=2))
        return

    title = f"Metrics matching '{pattern}'" if pattern else "All metrics"
    info(f"{title} ({len(values)} total)")
    for v in values:
        click.echo(v)
