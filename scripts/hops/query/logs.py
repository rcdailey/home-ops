"""VictoriaLogs query CLI (port of query-victorialogs.py).

Queries VictoriaLogs using LogSQL syntax via kubectl exec.
All functionality preserved from the original script.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

import click

from hops._format import info
from hops._runner import run

VL_URL = "http://victoria-logs-single.observability:9428"


class VictoriaLogsClient:
    """Client for querying VictoriaLogs."""

    def __init__(self, base_url: str = VL_URL):
        self.base_url = base_url.rstrip("/")

    def _post(self, endpoint: str, params: dict[str, str]) -> str:
        """POST to VictoriaLogs via kubectl exec with curl."""
        url = f"{self.base_url}{endpoint}"
        data = urllib.parse.urlencode(params)
        cmd = [
            "kubectl",
            "exec",
            "-n",
            "rook-ceph",
            "deploy/rook-ceph-tools",
            "--",
            "curl",
            "-sS",
            "-X",
            "POST",
            "--data",
            data,
            url,
        ]
        result = run(cmd, timeout=60, check=False)
        if result.returncode != 0:
            msg = (result.stderr or "").strip().split("\n")[0]
            info(f"error: VictoriaLogs query failed: {msg}")
            sys.exit(1)
        return result.stdout

    def _post_json(self, endpoint: str, params: dict[str, str]) -> Any:
        raw = self._post(endpoint, params)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            info("error: invalid JSON from VictoriaLogs")
            sys.exit(1)

    def query_logs(
        self,
        query: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"query": query}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if limit:
            params["limit"] = str(limit)
        raw = self._post("/select/logsql/query", params)
        logs = []
        for line in raw.strip().split("\n"):
            line = line.strip()
            if line:
                try:
                    logs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return logs

    def query_stats(self, query: str, time: str | None = None) -> Any:
        params: dict[str, str] = {"query": query}
        if time:
            params["time"] = time
        return self._post_json("/select/logsql/stats_query", params)

    def query_stats_range(
        self,
        query: str,
        start: str | None = None,
        end: str | None = None,
        step: str = "1h",
    ) -> Any:
        params: dict[str, str] = {"query": query, "step": step}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        return self._post_json("/select/logsql/stats_query_range", params)

    def query_hits(
        self,
        query: str,
        start: str | None = None,
        end: str | None = None,
        step: str = "1h",
        field: list[str] | None = None,
    ) -> Any:
        params: dict[str, str] = {"query": query, "step": step}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        # Handle multiple field parameters by constructing raw data
        if field:
            data_parts = [
                f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items()
            ]
            for f in field:
                data_parts.append(f"field={urllib.parse.quote(f)}")
            raw_data = "&".join(data_parts)
            url = f"{self.base_url}/select/logsql/hits"
            cmd = [
                "kubectl",
                "exec",
                "-n",
                "rook-ceph",
                "deploy/rook-ceph-tools",
                "--",
                "curl",
                "-sS",
                "-X",
                "POST",
                "--data",
                raw_data,
                url,
            ]
            result = run(cmd, timeout=60, check=False)
            if result.returncode != 0:
                info("error: VictoriaLogs query failed")
                sys.exit(1)
            return json.loads(result.stdout)
        return self._post_json("/select/logsql/hits", params)

    def query_field_names(
        self,
        query: str,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"query": query}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        result = self._post_json("/select/logsql/field_names", params)
        return result.get("values", [])


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
@click.option("--start", help="Start time (e.g., 5m, 1h, ISO timestamp)")
@click.option("--end", help="End time")
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
    start: str | None,
    end: str | None,
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
        query = build_query_from_filters(app, namespace, pod, container, level, search)
    elif logsql:
        query = logsql
    else:
        info("error: provide basic filters (--app, --level) or a LogSQL query")
        raise SystemExit(1)

    client = VictoriaLogsClient()
    logs = client.query_logs(query, start=start, end=end, limit=limit)

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
@click.option("--end", help="Timestamp for the query")
def stats(query: str, end: str | None):
    """Query log statistics (requires stats pipe in query)."""
    client = VictoriaLogsClient()
    result = client.query_stats(query, time=end)
    print(json.dumps(result, indent=2))


@cli.command("stats-range")
@click.argument("query")
@click.option("--start", help="Start time")
@click.option("--end", help="End time")
@click.option("--step", default="1h", help="Aggregation interval")
def stats_range(query: str, start: str | None, end: str | None, step: str):
    """Query log statistics over a time range."""
    client = VictoriaLogsClient()
    result = client.query_stats_range(query, start=start, end=end, step=step)
    print(json.dumps(result, indent=2))


@cli.command()
@click.argument("query")
@click.option("--start", help="Start time")
@click.option("--end", help="End time")
@click.option("--step", default="1h", help="Time bucket size")
@click.option("--field", multiple=True, help="Group by field (repeatable)")
def hits(
    query: str, start: str | None, end: str | None, step: str, field: tuple[str, ...]
):
    """Query hit statistics over time."""
    client = VictoriaLogsClient()
    result = client.query_hits(
        query, start=start, end=end, step=step, field=list(field) if field else None
    )
    print(json.dumps(result, indent=2))


@cli.command()
@click.argument("query")
@click.option("--start", help="Start time")
@click.option("--end", help="End time")
def fields(query: str, start: str | None, end: str | None):
    """List field names from query results."""
    client = VictoriaLogsClient()
    result = client.query_field_names(query, start=start, end=end)
    for field in result:
        print(f"{field['value']:30s} {field['hits']:>12,} hits")
