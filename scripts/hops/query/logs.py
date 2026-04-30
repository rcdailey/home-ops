"""VictoriaLogs query CLI (port of query-victorialogs.py).

Queries VictoriaLogs using LogSQL syntax via kubectl exec.
"""

from __future__ import annotations

import json
from datetime import datetime

import click

from hops._format import info, table
from hops._workload import resolve_app
from hops.query._client import VictoriaLogsClient


def format_log_entry(log: dict, detail: bool = False, all_fields: bool = False) -> str:
    """Format a log entry for display."""
    timestamp = log.get("_time", "")
    message = log.get("message", log.get("_msg", log.get("msg", "")))
    level = log.get("level", "")
    stream = log.get("stream", "")

    formatted_time = ""
    if timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            formatted_time = timestamp

    if all_fields:
        return json.dumps(log, indent=2)

    if detail:
        parts = []
        header_parts = []
        if formatted_time:
            header_parts.append(formatted_time)
        if level:
            header_parts.append(f"[{level.upper()}]")
        app = log.get("app", "")
        if app:
            header_parts.append(app)
        parts.append(" ".join(header_parts))

        core_fields = {"timestamp", "level", "stream", "message", "app"}
        internal_fields = {"_time", "_msg", "_stream", "_stream_id"}
        for key, value in sorted(log.items()):
            if (
                key in core_fields
                or key in internal_fields
                or key.startswith("kubernetes.")
            ):
                continue
            parts.append(f"  {key}: {value}")
        for key in sorted(k for k in log if k.startswith("kubernetes.")):
            parts.append(f"  {key}: {log[key]}")
        return "\n".join(parts)

    # Compact format
    parts = [formatted_time] if formatted_time else []
    if level:
        parts.append(f"[{level.upper()}]")
    if stream:
        parts.append(f"({stream})")
    parts.append(message)
    return " ".join(parts)


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


# --- Display helpers ---


def _format_metric_label(metric: dict[str, str]) -> str:
    """Compact label string from a stats metric dict."""
    filtered = {k: v for k, v in metric.items() if k != "__name__"}
    if not filtered:
        return "(all)"
    if len(filtered) == 1:
        return next(iter(filtered.values())) or "(empty)"
    return ", ".join(f"{k}={v}" for k, v in filtered.items())


def _format_ts(ts: str | float) -> str:
    """Format a timestamp (ISO string or epoch) to HH:MM."""
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.strftime("%H:%M")
        except (ValueError, TypeError):
            return str(ts)
    try:
        dt = datetime.fromtimestamp(float(ts), tz=datetime.now().astimezone().tzinfo)
        return dt.strftime("%H:%M")
    except (ValueError, TypeError, OSError):
        return str(ts)


def _print_vector(results: list[dict]) -> None:
    """Format Prometheus-style vector results as a table."""
    if not results:
        info("No results")
        return
    rows = []
    for r in results:
        label = _format_metric_label(r.get("metric", {}))
        val = r.get("value", [None, "N/A"])
        try:
            v = float(val[1])
            value_str = str(int(v)) if v == int(v) else f"{v:.2f}"
        except (ValueError, TypeError, IndexError):
            value_str = str(val[1]) if len(val) > 1 else "N/A"
        rows.append([label, value_str])
    stat_name = results[0].get("metric", {}).get("__name__", "VALUE")
    table(["METRIC", stat_name], rows)


def _print_matrix_table(results: list[dict]) -> None:
    """Format Prometheus-style matrix results as a time-series table."""
    if not results:
        info("No results")
        return

    # Collect all timestamps across all series
    all_ts: list[float] = []
    for r in results:
        for ts, _ in r.get("values", []):
            all_ts.append(float(ts))
    all_ts = sorted(set(all_ts))

    if not all_ts:
        info("No data points")
        return

    # Limit columns for readability
    max_cols = 12
    if len(all_ts) > max_cols:
        step = len(all_ts) // max_cols
        sampled = all_ts[::step][:max_cols]
        info(f"({len(all_ts)} points, showing {len(sampled)} samples)")
    else:
        sampled = all_ts

    time_headers = [_format_ts(ts) for ts in sampled]
    headers = ["METRIC"] + time_headers

    rows = []
    for r in results:
        label = _format_metric_label(r.get("metric", {}))
        val_map = {float(ts): val for ts, val in r.get("values", [])}
        cells = []
        for ts in sampled:
            raw = val_map.get(ts)
            if raw is None:
                cells.append("-")
            else:
                try:
                    v = float(raw)
                    cells.append(str(int(v)) if v == int(v) else f"{v:.2f}")
                except (ValueError, TypeError):
                    cells.append(str(raw))
        rows.append([label] + cells)

    table(headers, rows)


def _print_hits_table(data: dict) -> None:
    """Format VictoriaLogs hits response as a time-series table."""
    hit_list = data.get("hits", [])
    if not hit_list:
        info("No hits")
        return

    for hit in hit_list:
        fields = hit.get("fields", {})
        timestamps = hit.get("timestamps", [])
        values = hit.get("values", [])
        total = hit.get("total", sum(values))

        if fields:
            label = ", ".join(f"{k}={v}" for k, v in fields.items())
        else:
            label = "(all)"

        info(f"{label}  total={total}")
        if timestamps:
            rows = []
            for ts, val in zip(timestamps, values):
                rows.append([_format_ts(ts), str(val)])
            table(["TIME", "COUNT"], rows)


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
