#!/usr/bin/env python3
"""
VictoriaLogs query CLI - Query logs using LogSQL syntax.

Basic Usage:
    # Last 10 logs from an app
    ./scripts/query-victorialogs.py --app cloudflare-tunnel -10

    # Filter app logs by level
    ./scripts/query-victorialogs.py --app kometa --level error -20

    # Filter by namespace
    ./scripts/query-victorialogs.py --namespace observability --start 5m

Advanced Usage (LogSQL):
    # Custom LogSQL query
    ./scripts/query-victorialogs.py "error" --start 1h --limit 50

    # Complex filters
    ./scripts/query-victorialogs.py '{app="nginx"} AND error' --start 5m

    # Statistics
    ./scripts/query-victorialogs.py --stats "error | stats by(level) count(*)"

    # Hits over time
    ./scripts/query-victorialogs.py --hits "error" --start 3h --step 1h

Note: Uses cluster-internal service by default. Use --url for external access.
"""

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional


class VictoriaLogsClient:
    """Client for querying VictoriaLogs."""

    def __init__(self, base_url: str = "http://victoria-logs-single.observability:9428"):
        self.base_url = base_url.rstrip("/")

    def query_logs(
        self,
        query: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Query logs using LogSQL.

        Args:
            query: LogSQL query string
            start: Start timestamp (e.g., '5m', '1h', '2024-01-01T00:00:00Z')
            end: End timestamp
            limit: Maximum number of results

        Returns:
            List of log entries as dictionaries
        """
        endpoint = f"{self.base_url}/select/logsql/query"
        params = {"query": query}

        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if limit:
            params["limit"] = str(limit)

        data = urllib.parse.urlencode(params).encode("utf-8")

        try:
            with urllib.request.urlopen(endpoint, data=data) as response:
                # Response is newline-delimited JSON (NDJSON)
                logs = []
                for line in response:
                    line = line.decode("utf-8").strip()
                    if line:
                        logs.append(json.loads(line))
                return logs
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise Exception(f"HTTP {e.code}: {error_body}")
        except Exception as e:
            raise Exception(f"Query failed: {e}")

    def query_stats(
        self,
        query: str,
        time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Query log statistics at a specific time.

        Args:
            query: LogSQL query with stats pipe (e.g., "* | stats by(level) count(*)")
            time: Timestamp for the query (defaults to current time)

        Returns:
            Prometheus-compatible instant query result
        """
        endpoint = f"{self.base_url}/select/logsql/stats_query"
        params = {"query": query}

        if time:
            params["time"] = time

        data = urllib.parse.urlencode(params).encode("utf-8")

        try:
            with urllib.request.urlopen(endpoint, data=data) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise Exception(f"HTTP {e.code}: {error_body}")

    def query_stats_range(
        self,
        query: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        step: str = "1h",
    ) -> Dict[str, Any]:
        """
        Query log statistics over a time range.

        Args:
            query: LogSQL query with stats pipe
            start: Start timestamp
            end: End timestamp
            step: Time interval for aggregation (e.g., '1h', '6h', '1d')

        Returns:
            Prometheus-compatible range query result
        """
        endpoint = f"{self.base_url}/select/logsql/stats_query_range"
        params = {"query": query, "step": step}

        if start:
            params["start"] = start
        if end:
            params["end"] = end

        data = urllib.parse.urlencode(params).encode("utf-8")

        try:
            with urllib.request.urlopen(endpoint, data=data) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise Exception(f"HTTP {e.code}: {error_body}")

    def query_hits(
        self,
        query: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        step: str = "1h",
        field: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Query hit statistics over time.

        Args:
            query: LogSQL query string
            start: Start timestamp
            end: End timestamp
            step: Time bucket size (e.g., '1h', '1d')
            field: Optional field names to group by

        Returns:
            Hits statistics grouped by time buckets and optional fields
        """
        endpoint = f"{self.base_url}/select/logsql/hits"
        params = {"query": query, "step": step}

        if start:
            params["start"] = start
        if end:
            params["end"] = end

        # Handle multiple field parameters
        data_parts = [f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items()]
        if field:
            for f in field:
                data_parts.append(f"field={urllib.parse.quote(f)}")

        data = "&".join(data_parts).encode("utf-8")

        try:
            with urllib.request.urlopen(endpoint, data=data) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise Exception(f"HTTP {e.code}: {error_body}")

    def query_field_names(
        self,
        query: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get field names from query results.

        Args:
            query: LogSQL query string
            start: Start timestamp
            end: End timestamp

        Returns:
            List of field names with hit counts
        """
        endpoint = f"{self.base_url}/select/logsql/field_names"
        params = {"query": query}

        if start:
            params["start"] = start
        if end:
            params["end"] = end

        data = urllib.parse.urlencode(params).encode("utf-8")

        try:
            with urllib.request.urlopen(endpoint, data=data) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result.get("values", [])
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise Exception(f"HTTP {e.code}: {error_body}")


def format_log_entry(log: Dict[str, Any], show_all_fields: bool = False, show_detail: bool = False) -> str:
    """Format a log entry for display."""
    timestamp = log.get("_time", "")
    message = log.get("message", log.get("_msg", log.get("msg", "")))

    # Extract key fields
    level = log.get("level", "")
    stream = log.get("stream", "")
    app = log.get("app", "")

    # Format timestamp
    formatted_time = ""
    if timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            formatted_time = timestamp

    if show_all_fields:
        return json.dumps(log, indent=2)

    if show_detail:
        # Detailed format showing VRL-processed fields
        parts = []

        # Header line with timestamp, level, app
        header_parts = []
        if formatted_time:
            header_parts.append(formatted_time)
        if level:
            header_parts.append(f"[{level.upper()}]")
        if app:
            header_parts.append(app)

        parts.append(" ".join(header_parts))

        # Core fields
        core_fields = ["timestamp", "level", "stream", "message", "app"]
        k8s_fields = [k for k in log.keys() if k.startswith("kubernetes.")]
        internal_fields = ["_time", "_msg", "_stream", "_stream_id"]

        # Show all non-core, non-k8s, non-internal fields (VRL-extracted)
        for key, value in sorted(log.items()):
            if key in core_fields or key in k8s_fields or key in internal_fields:
                continue
            parts.append(f"  {key}: {value}")

        # Add kubernetes fields at the end
        for key in sorted(k8s_fields):
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


def detect_victorialogs_url() -> str:
    """Auto-detect VictoriaLogs URL (HTTPRoute or cluster-internal)."""
    try:
        # Try HTTPRoute first (external access)
        result = subprocess.run(
            ["kubectl", "get", "httproute", "-n", "observability", "victoria-logs",
             "-o", "jsonpath={.spec.hostnames[0]}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            hostname = result.stdout.strip()
            return f"https://{hostname}"
    except Exception:
        pass

    # Fallback to cluster-internal service
    return "http://victoria-logs-single.observability:9428"


def build_query_from_filters(
    app: Optional[str] = None,
    namespace: Optional[str] = None,
    pod: Optional[str] = None,
    container: Optional[str] = None,
    level: Optional[str] = None,
    search: Optional[str] = None,
) -> str:
    """Build LogSQL query from basic filters."""
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

    if filters:
        query = "{" + ",".join(filters) + "}"
    else:
        query = "*"

    if search:
        query = f"{query} AND {search}"

    return query


def main():
    parser = argparse.ArgumentParser(
        description="Query VictoriaLogs using LogSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Basic filter options
    basic_group = parser.add_argument_group("Basic Filters")
    basic_group.add_argument(
        "--app",
        help="Filter by app label",
    )
    basic_group.add_argument(
        "--namespace",
        help="Filter by Kubernetes namespace",
    )
    basic_group.add_argument(
        "--pod",
        help="Filter by pod name",
    )
    basic_group.add_argument(
        "--container",
        help="Filter by container name",
    )
    basic_group.add_argument(
        "--level",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Filter by log level",
    )
    basic_group.add_argument(
        "--search",
        help="Additional search term to filter messages",
    )

    # Common options (before positional to allow negative numbers)
    parser.add_argument(
        "-n",
        type=int,
        metavar="NUM",
        dest="tail_limit",
        help="Show last N log entries (shorthand for --limit)",
    )

    # Advanced LogSQL query
    advanced_group = parser.add_argument_group("Advanced Options")
    advanced_group.add_argument(
        "query",
        nargs="?",
        help="LogSQL query string (e.g., 'error', '{app=\"nginx\"} AND error')",
    )
    parser.add_argument(
        "--url",
        help="VictoriaLogs base URL (auto-detects: HTTPRoute if available, else cluster-internal)",
    )
    parser.add_argument(
        "--start",
        help="Start timestamp (e.g., '5m', '1h', '2024-01-01T00:00:00Z')",
    )
    parser.add_argument(
        "--end",
        help="End timestamp",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of results",
    )

    # Stats options
    stats_group = parser.add_argument_group("Statistics Options")
    stats_group.add_argument(
        "--stats",
        metavar="QUERY",
        help="Query statistics (requires stats pipe in query)",
    )
    stats_group.add_argument(
        "--stats-range",
        metavar="QUERY",
        help="Query statistics over time range",
    )
    stats_group.add_argument(
        "--hits",
        action="store_true",
        help="Query hit statistics over time",
    )
    stats_group.add_argument(
        "--step",
        default="1h",
        help="Time step for stats/hits queries (default: 1h)",
    )
    stats_group.add_argument(
        "--field",
        action="append",
        help="Group hits by field (can be specified multiple times)",
    )
    stats_group.add_argument(
        "--fields",
        action="store_true",
        help="List field names from query results",
    )

    # Output options
    output_group = parser.add_argument_group("Output Options")
    output_group.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON",
    )
    output_group.add_argument(
        "--detail",
        action="store_true",
        help="Show detailed view with all VRL-processed fields",
    )
    output_group.add_argument(
        "--all-fields",
        action="store_true",
        help="Show all fields as raw JSON",
    )

    # Misc
    parser.add_argument(
        "--via-kubectl",
        action="store_true",
        help="Access via kubectl exec (not port-forward per CLAUDE.md)",
    )

    args = parser.parse_args()

    # Handle -n shorthand
    if args.tail_limit:
        if args.limit:
            parser.error("Cannot use both -n and --limit")
        args.limit = args.tail_limit

    # Build query from basic filters or use advanced query
    has_basic_filters = any([args.app, args.namespace, args.pod, args.container, args.level, args.search])
    has_advanced_query = args.query is not None

    # Check if query looks like a negative number (misinterpreted -n argument)
    if has_advanced_query and args.query.startswith("-") and args.query[1:].isdigit():
        parser.error(
            f"Did you mean '-n {args.query[1:]}' instead of '{args.query}'? "
            "Use: --app APP -n NUM (not --app APP -NUM)"
        )

    if has_basic_filters and has_advanced_query:
        parser.error("Cannot mix basic filters (--app, --namespace, etc.) with advanced query")

    if has_basic_filters:
        query = build_query_from_filters(
            app=args.app,
            namespace=args.namespace,
            pod=args.pod,
            container=args.container,
            level=args.level,
            search=args.search,
        )
    elif has_advanced_query:
        query = args.query
    elif args.stats or args.stats_range:
        query = None
    else:
        parser.error("Either specify basic filters (--app, --namespace, etc.) or provide a LogSQL query")

    # Handle kubectl exec access method
    if args.via_kubectl:
        print(
            "Note: For kubectl access, use 'kubectl exec' with curl:\n"
            "kubectl exec -n observability victoria-logs-single-0 -c vlogs -- "
            "wget -qO- 'http://localhost:9428/select/logsql/query' --post-data 'query=error'",
            file=sys.stderr,
        )
        return 1

    try:
        # Auto-detect URL if not provided
        url = args.url or detect_victorialogs_url()
        client = VictoriaLogsClient(url)

        if args.stats:
            result = client.query_stats(args.stats, time=args.end)
            print(json.dumps(result, indent=2))

        elif args.stats_range:
            result = client.query_stats_range(
                args.stats_range,
                start=args.start,
                end=args.end,
                step=args.step,
            )
            print(json.dumps(result, indent=2))

        elif args.hits:
            if not query:
                parser.error("--hits requires a query (use basic filters or advanced query)")
            result = client.query_hits(
                query,
                start=args.start,
                end=args.end,
                step=args.step,
                field=args.field,
            )
            print(json.dumps(result, indent=2))

        elif args.fields:
            if not query:
                parser.error("--fields requires a query (use basic filters or advanced query)")
            result = client.query_field_names(
                query,
                start=args.start,
                end=args.end,
            )
            for field in result:
                print(f"{field['value']:30s} {field['hits']:>12,} hits")

        else:
            logs = client.query_logs(
                query,
                start=args.start,
                end=args.end,
                limit=args.limit,
            )

            if args.json:
                for log in logs:
                    print(json.dumps(log))
            else:
                for i, log in enumerate(logs):
                    if i > 0 and args.detail:
                        print()  # Blank line between detailed entries
                    print(format_log_entry(log, args.all_fields, args.detail))

            # Print summary to stderr
            print(f"\nTotal: {len(logs)} log entries", file=sys.stderr)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
