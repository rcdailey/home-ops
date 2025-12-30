#!/usr/bin/env python3

"""Query VictoriaMetrics and vmalert for metrics and alerts.

Examples:
  # Container metrics
  %(prog)s cpu media 'plex.*' plex 7d
  %(prog)s memory default 'homepage.*' app 24h

  # Raw PromQL queries
  %(prog)s query 'up{job="kubelet"}'
  %(prog)s query 'rate(http_requests_total[5m])' --range --start 2025-01-01T00:00:00Z --end 2025-01-01T01:00:00Z

  # Discovery
  %(prog)s labels                    # List all label names
  %(prog)s labels namespace          # List values for 'namespace' label
  %(prog)s metrics --filter cpu      # Find CPU-related metrics

  # Alerts
  %(prog)s alerts --state firing     # List firing alerts
  %(prog)s alert Watchdog            # Alert details
  %(prog)s history 24h               # Alert firing frequency
"""

import argparse
import json
import subprocess
import sys
from typing import Any
from urllib.parse import urlencode

VMSINGLE_URL = "http://vmsingle-victoria-metrics-k8s-stack.observability:8428"
VMALERT_URL = "http://vmalert-victoria-metrics-k8s-stack.observability:8080"

COLORS = {
    "blue": "\033[0;34m",
    "green": "\033[0;32m",
    "yellow": "\033[1;33m",
    "red": "\033[0;31m",
    "reset": "\033[0m",
}

SEVERITY_COLORS = {"critical": "red", "warning": "yellow", "info": "blue", "none": "blue"}
IGNORED_ALERTS = {"Watchdog", "InfoInhibitor"}

# Global JSON output mode
_json_mode = False


def colorize(text: str, color: str) -> str:
    """Wrap text in ANSI color codes."""
    if _json_mode:
        return text
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


def kubectl_curl(url: str) -> dict[str, Any]:
    """Execute curl via rook-ceph-tools deployment."""
    cmd = ["kubectl", "exec", "-n", "rook-ceph", "deploy/rook-ceph-tools", "--", "curl", "-s", url]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def query_vm(endpoint: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    """Query VictoriaMetrics API."""
    url = f"{VMSINGLE_URL}{endpoint}"
    if params:
        url = f"{url}?{urlencode(params)}"
    return kubectl_curl(url)


def query_vmalert(endpoint: str) -> dict[str, Any]:
    """Query vmalert API."""
    return kubectl_curl(f"{VMALERT_URL}{endpoint}")


def parse_duration(duration: str) -> int:
    """Convert duration string (e.g., '7d', '24h', '30m') to seconds."""
    unit = duration[-1]
    value = int(duration[:-1])
    if unit == "d":
        return value * 86400
    elif unit == "h":
        return value * 3600
    elif unit == "m":
        return value * 60
    raise ValueError(f"Invalid duration unit: {unit}. Use d, h, or m")


def format_cpu(value: float) -> str:
    """Format CPU value as millicores or cores."""
    if value < 0.001:
        return f"{value * 1000000:.0f}u"
    elif value < 1:
        return f"{value * 1000:.0f}m"
    return f"{value:.2f}"


def format_memory(value: float) -> str:
    """Format memory in human-readable units."""
    for unit in ["B", "Ki", "Mi", "Gi", "Ti"]:
        if value < 1024.0:
            return f"{value:.1f}{unit}"
        value /= 1024.0
    return f"{value:.1f}Pi"


def format_labels(labels: dict[str, str], exclude: set[str] | None = None) -> list[str]:
    """Format labels as key=value pairs."""
    exclude = exclude or set()
    return [f"{k}={v}" for k, v in labels.items() if k not in exclude]


def container_stats(
    namespace: str, pod: str, container: str, duration: str, metric: str, rate: str | None = None
) -> dict[str, float | None]:
    """Query current/max/avg for a container metric."""
    selector = f'namespace="{namespace}",pod=~"{pod}",container="{container}"'
    base = f"{metric}{{{selector}}}"
    expr = f"rate({base}[{rate}])" if rate else base

    stats: dict[str, float | None] = {"current": None, "max": None, "avg": None}

    # Current
    data = query_vm("/api/v1/query", {"query": expr})
    results = data.get("data", {}).get("result", [])
    if results:
        stats["current"] = float(results[0]["value"][1])

    # Max over duration
    data = query_vm("/api/v1/query", {"query": f"max_over_time({expr}[{duration}:])"})
    results = data.get("data", {}).get("result", [])
    if results:
        stats["max"] = max(float(r["value"][1]) for r in results)

    # Avg over duration
    data = query_vm("/api/v1/query", {"query": f"avg_over_time({expr}[{duration}:])"})
    results = data.get("data", {}).get("result", [])
    if results:
        stats["avg"] = sum(float(r["value"][1]) for r in results) / len(results)

    return stats


def cmd_cpu(args: argparse.Namespace) -> None:
    """Query CPU usage statistics."""
    if not _json_mode:
        print(colorize(f"Querying CPU for {args.namespace}/{args.pod}/{args.container}...\n", "blue"))

    stats = container_stats(
        args.namespace, args.pod, args.container, args.duration,
        "container_cpu_usage_seconds_total", rate="5m"
    )

    # CPU throttling
    selector = f'namespace="{args.namespace}",pod=~"{args.pod}",container="{args.container}"'
    throttle_query = f"""
    (sum(increase(container_cpu_cfs_throttled_periods_total{{{selector}}}[{args.duration}]))
     / sum(increase(container_cpu_cfs_periods_total{{{selector}}}[{args.duration}]))) * 100
    """
    throttle_data = query_vm("/api/v1/query", {"query": throttle_query})
    throttle_results = throttle_data.get("data", {}).get("result", [])
    throttle_pct = float(throttle_results[0]["value"][1]) if throttle_results else None

    if _json_mode:
        print(json.dumps({"cpu": stats, "throttle_percent": throttle_pct}, indent=2))
        return

    if stats["current"] is not None:
        print(f"Current (5m rate): {format_cpu(stats['current'])} cores")
    else:
        print("Current: No data")
    if stats["max"] is not None:
        print(f"Max ({args.duration}):     {format_cpu(stats['max'])} cores")
    if stats["avg"] is not None:
        print(f"Avg ({args.duration}):     {format_cpu(stats['avg'])} cores")
    if throttle_pct is not None:
        color = "red" if throttle_pct > 25 else "yellow" if throttle_pct > 10 else "green"
        print(f"Throttled ({args.duration}): " + colorize(f"{throttle_pct:.2f}%", color))


def cmd_memory(args: argparse.Namespace) -> None:
    """Query memory usage statistics."""
    if not _json_mode:
        print(colorize(f"Querying memory for {args.namespace}/{args.pod}/{args.container}...\n", "blue"))

    stats = container_stats(
        args.namespace, args.pod, args.container, args.duration,
        "container_memory_working_set_bytes"
    )

    if _json_mode:
        print(json.dumps({"memory": stats}, indent=2))
        return

    if stats["current"] is not None:
        print(f"Current: {format_memory(stats['current'])}")
    else:
        print("Current: No data")
    if stats["max"] is not None:
        print(f"Max ({args.duration}): {format_memory(stats['max'])}")
    if stats["avg"] is not None:
        print(f"Avg ({args.duration}): {format_memory(stats['avg'])}")


def cmd_query(args: argparse.Namespace) -> None:
    """Execute raw PromQL query."""
    if args.range:
        params = {"query": args.promql, "start": args.start, "end": args.end, "step": args.step}
        data = query_vm("/api/v1/query_range", params)
    else:
        data = query_vm("/api/v1/query", {"query": args.promql})

    if _json_mode:
        print(json.dumps(data, indent=2))
        return

    results = data.get("data", {}).get("result", [])
    result_type = data.get("data", {}).get("resultType", "unknown")

    if not results:
        print(colorize("No results", "yellow"))
        return

    print(colorize(f"Result type: {result_type}, {len(results)} series\n", "blue"))

    for r in results[:20]:  # Limit output
        metric = r.get("metric", {})
        labels = ", ".join(f"{k}={v}" for k, v in metric.items())
        if result_type == "matrix":
            values = r.get("values", [])
            print(f"{{{labels}}}")
            for ts, val in values[:10]:
                print(f"  {ts}: {val}")
            if len(values) > 10:
                print(f"  ... ({len(values)} total points)")
        else:
            value = r.get("value", [None, "N/A"])
            print(f"{{{labels}}} => {value[1]}")

    if len(results) > 20:
        print(colorize(f"\n... {len(results) - 20} more series", "yellow"))


def cmd_labels(args: argparse.Namespace) -> None:
    """List label names or values."""
    if args.name:
        data = query_vm(f"/api/v1/label/{args.name}/values")
        title = f"Values for label '{args.name}'"
    else:
        data = query_vm("/api/v1/labels")
        title = "All labels"

    values = data.get("data", [])

    if _json_mode:
        print(json.dumps(values, indent=2))
        return

    print(colorize(f"{title} ({len(values)} total)\n", "blue"))
    for v in values:
        print(v)


def cmd_metrics(args: argparse.Namespace) -> None:
    """List metric names with optional filter."""
    data = query_vm("/api/v1/label/__name__/values")
    values = data.get("data", [])

    if args.filter:
        pattern = args.filter.lower()
        values = [v for v in values if pattern in v.lower()]

    if _json_mode:
        print(json.dumps(values, indent=2))
        return

    title = f"Metrics matching '{args.filter}'" if args.filter else "All metrics"
    print(colorize(f"{title} ({len(values)} total)\n", "blue"))
    for v in values:
        print(v)


def cmd_alerts(args: argparse.Namespace) -> None:
    """List alerts filtered by state."""
    data = query_vmalert("/api/v1/alerts")
    alerts = data.get("data", {}).get("alerts", [])

    states = ["firing", "pending", "inactive"] if args.state == "all" else [args.state]
    filtered = [
        a for a in alerts
        if a.get("state") in states and a.get("labels", {}).get("alertname") not in IGNORED_ALERTS
    ]

    if _json_mode:
        print(json.dumps(filtered, indent=2))
        return

    if not filtered:
        print(colorize(f"No alerts in {args.state} state", "green"))
        return

    for alert in filtered:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        severity = labels.get("severity", "none")
        color = SEVERITY_COLORS.get(severity, "reset")

        print(colorize(f"[{severity}]", color), f"{labels.get('alertname')} ({alert.get('state')})")
        print(f"  {annotations.get('summary', annotations.get('description', 'No description'))}")
        print(f"  Expression: {alert.get('expression', 'N/A')}")

        relevant = format_labels(labels, exclude={"alertname", "alertgroup", "prometheus", "severity"})
        if relevant:
            print("  Labels:", ", ".join(relevant[:5]))
        print()


def cmd_alert(args: argparse.Namespace) -> None:
    """Show detailed alert information."""
    data = query_vmalert("/api/v1/alerts")
    alerts = [a for a in data.get("data", {}).get("alerts", [])
              if a.get("labels", {}).get("alertname") == args.name]

    if not alerts:
        print(colorize(f"No alert found: {args.name}", "red"), file=sys.stderr)
        sys.exit(1)

    alert = alerts[0]

    if _json_mode:
        print(json.dumps(alert, indent=2))
        return

    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})

    print(f"Alert: {labels.get('alertname')}")
    print(f"State: {alert.get('state')}")
    print(f"Severity: {labels.get('severity', 'none')}")
    print(f"Value: {alert.get('value', 'N/A')}")
    print(f"Active Since: {alert.get('activeAt', 'N/A')}")
    print(f"Expression: {alert.get('expression', 'N/A')}")
    print("\nLabels:")
    for k, v in labels.items():
        print(f"  {k}: {v}")
    print("\nAnnotations:")
    for k, v in annotations.items():
        print(f"  {k}: {v}")


def cmd_rules(args: argparse.Namespace) -> None:
    """List alert rules."""
    data = query_vmalert("/api/v1/rules")
    groups = data.get("data", {}).get("groups", [])

    if _json_mode:
        print(json.dumps(groups, indent=2))
        return

    for group in groups:
        print(f"Group: {group.get('name')}")
        print(f"Interval: {group.get('interval', 'N/A')}")
        print("Rules:")
        for rule in group.get("rules", []):
            print(f"  - {rule.get('name')} ({rule.get('type')}) - {rule.get('state')}")
        print()


def cmd_history(args: argparse.Namespace) -> None:
    """Show alert firing history."""
    if not _json_mode:
        title = f"Alert history for last {args.duration}"
        if args.alert:
            title += f" (filtered by {args.alert})"
        print(colorize(f"{title}...\n", "blue"))

    if args.alert:
        query = f'sum(changes(ALERTS{{alertstate="firing",alertname="{args.alert}"}}[{args.duration}])) by (alertname,severity,instance,namespace,job,pod,node)'
    else:
        query = f'topk(20, sum(changes(ALERTS{{alertstate="firing"}}[{args.duration}])) by (alertname,severity))'

    data = query_vm("/api/v1/query", {"query": query})
    results = data.get("data", {}).get("result", [])

    if _json_mode:
        print(json.dumps(results, indent=2))
        return

    if not results:
        print(colorize(f"No alerts fired in last {args.duration}", "green"))
        return

    results.sort(key=lambda x: float(x["value"][1]), reverse=True)

    for r in results:
        metric = r["metric"]
        count = int(float(r["value"][1]))
        if count == 0:
            continue

        severity = metric.get("severity", "none")
        color = SEVERITY_COLORS.get(severity, "reset")
        print(colorize(f"[{severity}]", color), f"{metric.get('alertname')} - Fired {count} times")

        if args.alert:
            relevant = format_labels(metric, exclude={"alertname", "severity", "__name__"})
            if relevant:
                for label in relevant:
                    print(f"    {label}")
            print()


def main() -> None:
    """Main entry point."""
    global _json_mode

    parser = argparse.ArgumentParser(
        description="Query VictoriaMetrics and vmalert",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # cpu
    p = subparsers.add_parser("cpu", help="CPU usage and throttling")
    p.add_argument("namespace", help="Namespace")
    p.add_argument("pod", help="Pod name pattern (regex)")
    p.add_argument("container", help="Container name")
    p.add_argument("duration", nargs="?", default="7d", help="Duration (default: 7d)")

    # memory
    p = subparsers.add_parser("memory", help="Memory usage")
    p.add_argument("namespace", help="Namespace")
    p.add_argument("pod", help="Pod name pattern (regex)")
    p.add_argument("container", help="Container name")
    p.add_argument("duration", nargs="?", default="7d", help="Duration (default: 7d)")

    # query
    p = subparsers.add_parser("query", help="Raw PromQL query")
    p.add_argument("promql", help="PromQL expression")
    p.add_argument("--range", action="store_true", help="Range query instead of instant")
    p.add_argument("--start", help="Start time (ISO8601 or Unix timestamp)")
    p.add_argument("--end", help="End time (ISO8601 or Unix timestamp)")
    p.add_argument("--step", default="1m", help="Step interval (default: 1m)")

    # labels
    p = subparsers.add_parser("labels", help="List labels or label values")
    p.add_argument("name", nargs="?", help="Label name (omit to list all labels)")

    # metrics
    p = subparsers.add_parser("metrics", help="List metric names")
    p.add_argument("--filter", "-f", help="Filter pattern (case-insensitive)")

    # alerts
    p = subparsers.add_parser("alerts", help="List alerts")
    p.add_argument("--state", "-s", default="firing", choices=["firing", "pending", "inactive", "all"])

    # alert
    p = subparsers.add_parser("alert", help="Alert details")
    p.add_argument("name", help="Alert name")

    # rules
    subparsers.add_parser("rules", help="List alert rules")

    # history
    p = subparsers.add_parser("history", help="Alert firing history")
    p.add_argument("duration", nargs="?", default="6h", help="Duration (default: 6h)")
    p.add_argument("--alert", "-a", help="Filter by alert name")

    args = parser.parse_args()
    _json_mode = args.json

    commands = {
        "cpu": cmd_cpu,
        "memory": cmd_memory,
        "query": cmd_query,
        "labels": cmd_labels,
        "metrics": cmd_metrics,
        "alerts": cmd_alerts,
        "alert": cmd_alert,
        "rules": cmd_rules,
        "history": cmd_history,
    }

    try:
        commands[args.command](args)
    except subprocess.CalledProcessError as e:
        print(colorize(f"Error: {e}", "red"), file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(colorize(f"JSON parse error: {e}", "red"), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(colorize(f"Unexpected error: {e}", "red"), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
