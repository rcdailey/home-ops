"""VictoriaLogs query CLI (port of query-victorialogs.py).

Queries VictoriaLogs using LogSQL syntax via kubectl exec.
"""

from __future__ import annotations

import json
import re

import click

from hops._click import HelpfulGroup
from hops.core.format import info
from hops.core.workload import Workload, resolve_app
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
    app_identity: str | None = None,
) -> str:
    filters = []
    if app_identity:
        filters.append(f"({app_identity})")
    elif app:
        filters.append(f'"service.name":={json.dumps(app)}')
    if namespace:
        filters.append(f'"k8s.namespace.name":={json.dumps(namespace)}')
    if pod:
        filters.append(f'"k8s.pod.name":={json.dumps(pod)}')
    if container:
        filters.append(f'"k8s.container.name":={json.dumps(container)}')
    if level:
        pattern = json.dumps(rf"(?i)^{re.escape(level)}$")
        filters.append(f'(level:={json.dumps(level)} or "severity_text":~{pattern})')
    query = " ".join(filters) if filters else "*"
    if search:
        query = f"{query} AND {search}"
    return query


_LOG_OPT_IN_LABEL = "observability.home-ops/logs"
_OTEL_SIDECAR_ANNOTATION = "sidecar.opentelemetry.io/inject"

_PLAIN_LEVELS: dict[str, tuple[re.Pattern[str], dict[str, str]]] = {
    "recyclarr": (
        re.compile(r"\[(VRB|DBG|INF|WRN|ERR|FTL)\]"),
        {
            "VRB": "debug",
            "DBG": "debug",
            "INF": "info",
            "WRN": "warning",
            "ERR": "error",
            "FTL": "critical",
        },
    ),
    "sabnzbd": (
        re.compile(r"::(DEBUG|INFO|WARNING|ERROR|CRITICAL)::"),
        {
            "DEBUG": "debug",
            "INFO": "info",
            "WARNING": "warning",
            "ERROR": "error",
            "CRITICAL": "critical",
        },
    ),
    "qbittorrent": (
        re.compile(r"\(([NIWC])\)"),
        {"N": "info", "I": "info", "W": "warning", "C": "critical"},
    ),
}


def _has_otel_sidecar(workload: Workload) -> bool:
    """Check whether the pod template requests an OpenTelemetry sidecar."""
    annotations = workload.pod_template().get("metadata", {}).get("annotations", {})
    value = annotations.get(_OTEL_SIDECAR_ANNOTATION)
    return value not in (None, "false")


def _require_log_collection(app: str) -> Workload:
    """Resolve an app and verify that its logs are configured for collection."""
    wl = resolve_app(app)
    if not wl:
        info(f"error: no workload matching {app!r} found in cluster")
        raise SystemExit(1)

    labels = wl.pod_labels()
    if labels.get(_LOG_OPT_IN_LABEL) == "true":
        return wl
    if _has_otel_sidecar(wl):
        return wl

    info(
        f"error: {wl.name} (namespace: {wl.namespace}) has no log collection; "
        "add pod label "
        f'"{_LOG_OPT_IN_LABEL}=true" for node collection '
        "or inject an OpenTelemetry sidecar"
    )
    info("hint: use 'hops app logs' for immediate kubectl-based access")
    raise SystemExit(1)


def _app_identity_filter(app: str, workload: Workload) -> str:
    """Build a query from canonical OpenTelemetry resource identity."""
    terms = {f'"service.name":={json.dumps(app)}'}
    if app_label := workload.app_label():
        terms.add(f'"service.name":={json.dumps(app_label)}')

    pod_pattern = rf"^{re.escape(workload.name)}(?:-|$)"
    pod_identity = (
        f'"k8s.namespace.name":={json.dumps(workload.namespace)} '
        f'"k8s.pod.name":~{json.dumps(pod_pattern)}'
    )
    terms.add(f"({pod_identity})")

    for container in workload.pod_spec().get("containers", []):
        name = container.get("name")
        if name in (None, "app", "main"):
            continue
        container_identity = (
            f'"k8s.namespace.name":={json.dumps(workload.namespace)} '
            f'"k8s.container.name":={json.dumps(name)}'
        )
        terms.add(f"({container_identity})")
    return " or ".join(sorted(terms))


def _log_app(log: dict) -> str:
    """Return the effective app identity from OpenTelemetry resource fields."""
    if value := log.get("service.name"):
        return str(value)

    pod_name = str(log.get("k8s.pod.name", ""))
    for app in _PLAIN_LEVELS:
        if pod_name == app or pod_name.startswith(f"{app}-"):
            return app
    return ""


def _audit_level(log: dict) -> str:
    """Derive API audit severity from the HTTP response status."""
    try:
        code = int(log["responseStatus.code"])
    except (KeyError, TypeError, ValueError):
        return "unknown"
    if code >= 500:
        return "error"
    if code >= 400:
        return "warning"
    return "info"


def normalize_log(log: dict, app_hint: str | None = None) -> dict:
    """Normalize diagnostic severity without changing stored records."""
    result = dict(log)
    app = _log_app(result) or app_hint or ""
    if app and not result.get("app"):
        result["app"] = app
    if not result.get("namespace") and result.get("k8s.namespace.name"):
        result["namespace"] = result["k8s.namespace.name"]

    if result.get("log_type") == "kubernetes-audit" or (
        result.get("kind") == "Event" and result.get("apiVersion") == "audit.k8s.io/v1"
    ):
        result["level"] = _audit_level(result)
        return result

    level_parser = _PLAIN_LEVELS.get(app)
    if level_parser:
        pattern, levels = level_parser
        message = str(result.get("_msg", result.get("message", "")))
        match = pattern.search(message)
        result["level"] = levels.get(match.group(1), "unknown") if match else "unknown"
        return result

    level = str(result.get("level") or result.get("severity_text", "")).lower()
    result["level"] = {"warn": "warning", "fatal": "critical"}.get(
        level, level or "unknown"
    )
    return result


# --- Click commands ---


@click.group(cls=HelpfulGroup)
def cli():
    """Query VictoriaLogs using LogSQL syntax."""


@cli.command("query")
@click.argument("logsql", required=False)
@click.option("--app", help="Filter by service name")
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
@click.option("--detail", is_flag=True, help="Show all structured fields")
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
        app_identity = None
        client_level_filter = bool(app in _PLAIN_LEVELS and level)
        if app:
            workload = _require_log_collection(app)
            app_identity = _app_identity_filter(app, workload)
        query = build_query_from_filters(
            app,
            namespace,
            pod,
            container,
            None if client_level_filter else level,
            search,
            app_identity,
        )
    elif logsql:
        query = logsql
        client_level_filter = False
    else:
        info("error: provide basic filters (--app, --level) or a LogSQL query")
        raise SystemExit(1)

    client = VictoriaLogsClient()
    server_limit = None if client_level_filter else limit
    logs = [
        normalize_log(log, app)
        for log in client.query_logs(
            query,
            start=time_from,
            end=time_to,
            limit=server_limit,
        )
    ]
    if client_level_filter:
        logs = [log for log in logs if log["level"] == level]
        if limit is not None:
            logs = logs[:limit]

    if json_mode:
        for log in logs:
            click.echo(json.dumps(log))
    else:
        for i, log in enumerate(logs):
            if i > 0 and detail:
                click.echo()
            click.echo(format_log_entry(log, detail=detail, all_fields=all_fields))

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
        click.echo(json.dumps(result, indent=2))
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
        click.echo(json.dumps(result, indent=2))
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
        click.echo(json.dumps(result, indent=2))
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
        click.echo(f"{field['value']:30s} {field['hits']:>12,} hits")
