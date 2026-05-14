"""VictoriaLogs query CLI (port of query-victorialogs.py).

Queries VictoriaLogs using LogSQL syntax via kubectl exec.
"""

from __future__ import annotations

import json

import click

from hops.core.format import info
from hops.core.workload import resolve_app
from hops.query._client import VictoriaLogsClient
from hops.query.logs_render import (
    _print_hits_table,
    _print_matrix_table,
    _print_vector,
    format_log_entry,
)


def build_query_from_filters(
    app: str | None = None,
    namespace: str | None = None,
    pod: str | None = None,
    container: str | None = None,
    level: str | None = None,
    search: str | None = None,
) -> str:
    filters = []
    if app:
        filters.append(f'app="{app}"')
    if namespace:
        filters.append(f'kubernetes.pod_namespace="{namespace}"')
    if pod:
        filters.append(f'kubernetes.pod_name="{pod}"')
    if container:
        filters.append(f'kubernetes.container_name="{container}"')
    if level:
        filters.append(f'level="{level}"')
    query = "{" + ",".join(filters) + "}" if filters else "*"
    if search:
        query = f"{query} AND {search}"
    return query


_VECTOR_OPT_IN_LABEL = "observability.home-ops/logs"
_VECTOR_SIDECAR_NAME = "vector"


def _has_vector_sidecar(pod_spec: dict) -> bool:
    """Check if the pod spec includes a Vector sidecar container."""
    for container_list in ("containers", "initContainers"):
        for c in pod_spec.get(container_list, []):
            if c.get("name") == _VECTOR_SIDECAR_NAME:
                return True
    return False


def _require_vector_collection(app: str) -> None:
    """Verify the app exists and Vector is collecting its logs."""
    wl = resolve_app(app)
    if not wl:
        info(f"error: no workload matching {app!r} found in cluster")
        raise SystemExit(1)

    labels = wl.pod_labels()
    pod_spec = wl.pod_spec()

    # Path 1: daemonset collection via opt-in label
    if labels.get(_VECTOR_OPT_IN_LABEL) == "true":
        return
    # Path 2: Vector sidecar container
    if _has_vector_sidecar(pod_spec):
        return

    info(
        f"error: {wl.name} (namespace: {wl.namespace}) has no Vector log collection; "
        "add pod label "
        f'"{_VECTOR_OPT_IN_LABEL}=true" for daemonset collection '
        "or a Vector sidecar container"
    )
    info("hint: use 'hops app logs' for immediate kubectl-based access")
    raise SystemExit(1)


# --- Click commands ---


@click.group()
def cli():
    """Query VictoriaLogs using LogSQL syntax."""


@cli.command("query")
@click.argument("logsql", required=False)
@click.option("--app", help="Filter by app label")
@click.option("--namespace", help="Filter by Kubernetes namespace")
@click.option("--pod", help="Filter by pod name")
@click.option("--container", help="Filter by container name")
@click.option(
    "--level",
    type=click.Choice(["debug", "info", "warning", "error", "critical"]),
    help="Filter by log level",
)
@click.option("--search", help="Additional search term")
@click.option("-n", "--limit", type=int, help="Max results")
@click.option("--from", "time_from", help="Start time (e.g., 5m, 1h, ISO timestamp)")
@click.option("--to", "time_to", help="End time")
@click.option("--detail", is_flag=True, help="Show all VRL-processed fields")
@click.option("--all-fields", is_flag=True, help="Show raw JSON per entry")
@click.option("--json", "json_mode", is_flag=True, help="Output NDJSON")
def query_cmd(
    logsql: str | None,
    app: str | None,
    namespace: str | None,
    pod: str | None,
    container: str | None,
    level: str | None,
    search: str | None,
    limit: int | None,
    time_from: str | None,
    time_to: str | None,
    detail: bool,
    all_fields: bool,
    json_mode: bool,
):
    """Query logs. Use filters (--app, --level) or raw LogSQL."""
    has_filters = any([app, namespace, pod, container, level, search])
    if has_filters and logsql:
        info("error: cannot mix basic filters with LogSQL query")
        raise SystemExit(1)

    if has_filters:
        if app:
            _require_vector_collection(app)
        query = build_query_from_filters(app, namespace, pod, container, level, search)
    elif logsql:
        query = logsql
    else:
        info("error: provide basic filters (--app, --level) or a LogSQL query")
        raise SystemExit(1)

    client = VictoriaLogsClient()
    logs = client.query_logs(query, start=time_from, end=time_to, limit=limit)

    if json_mode:
        for log in logs:
            print(json.dumps(log))
    else:
        for i, log in enumerate(logs):
            if i > 0 and detail:
                print()
            print(format_log_entry(log, detail=detail, all_fields=all_fields))

    info(f"\nTotal: {len(logs)} log entries")


@cli.command()
@click.argument("query")
@click.option("--from", "time_from", help="Start time (e.g., 5m, 1h, ISO timestamp)")
@click.option("--to", "time_to", help="End time")
@click.option("--json", "json_mode", is_flag=True, help="Output raw JSON")
def stats(query: str, time_from: str | None, time_to: str | None, json_mode: bool):
    """Query log statistics (requires stats pipe in query)."""
    client = VictoriaLogsClient()
    result = client.query_stats(query, start=time_from, end=time_to)
    if json_mode:
        print(json.dumps(result, indent=2))
        return
    results = result.get("data", {}).get("result", [])
    _print_vector(results)


@cli.command("stats-range")
@click.argument("query")
@click.option("--from", "time_from", help="Start time")
@click.option("--to", "time_to", help="End time")
@click.option("--step", default="1h", help="Aggregation interval")
@click.option("--json", "json_mode", is_flag=True, help="Output raw JSON")
def stats_range(
    query: str, time_from: str | None, time_to: str | None, step: str, json_mode: bool
):
    """Query log statistics over a time range."""
    client = VictoriaLogsClient()
    result = client.query_stats_range(query, start=time_from, end=time_to, step=step)
    if json_mode:
        print(json.dumps(result, indent=2))
        return
    results = result.get("data", {}).get("result", [])
    _print_matrix_table(results)


@cli.command()
@click.argument("query")
@click.option("--from", "time_from", help="Start time")
@click.option("--to", "time_to", help="End time")
@click.option("--step", default="1h", help="Time bucket size")
@click.option("--field", multiple=True, help="Group by field (repeatable)")
@click.option("--json", "json_mode", is_flag=True, help="Output raw JSON")
def hits(
    query: str,
    time_from: str | None,
    time_to: str | None,
    step: str,
    field: tuple[str, ...],
    json_mode: bool,
):
    """Query hit statistics over time."""
    client = VictoriaLogsClient()
    result = client.query_hits(
        query,
        start=time_from,
        end=time_to,
        step=step,
        field=list(field) if field else None,
    )
    if json_mode:
        print(json.dumps(result, indent=2))
        return
    _print_hits_table(result)


@cli.command()
@click.argument("query")
@click.option("--from", "time_from", help="Start time")
@click.option("--to", "time_to", help="End time")
def fields(query: str, time_from: str | None, time_to: str | None):
    """List field names from query results."""
    client = VictoriaLogsClient()
    result = client.query_field_names(query, start=time_from, end=time_to)
    for field in result:
        print(f"{field['value']:30s} {field['hits']:>12,} hits")
