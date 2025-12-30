#!/usr/bin/env python3

"""Query vmalert for alert information via ephemeral kubectl pods."""

import argparse
import json
import subprocess
import sys
from typing import Any
from urllib.parse import quote

VMALERT_URL = "http://vmalert-victoria-metrics-k8s-stack.observability:8080"
VMSINGLE_URL = "http://vmsingle-victoria-metrics-k8s-stack.observability:8428"
CURL_IMAGE = "curlimages/curl:latest"

COLORS = {
    "red": "\033[0;31m",
    "yellow": "\033[1;33m",
    "green": "\033[0;32m",
    "blue": "\033[0;34m",
    "reset": "\033[0m",
}

SEVERITY_COLORS = {
    "critical": "red",
    "warning": "yellow",
    "none": "blue",
}

# Alerts that are expected to always fire (health checks, inhibitors)
IGNORED_ALERTS = {"Watchdog", "InfoInhibitor"}


def kubectl_curl(url: str) -> dict[str, Any]:
    """Execute curl via rook-ceph-tools pod (used as utility pod, not for Ceph operations)."""
    cmd = [
        "kubectl",
        "exec",
        "-n",
        "rook-ceph",
        "deploy/rook-ceph-tools",
        "--",
        "curl",
        "-s",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def query_vmalert(endpoint: str) -> dict[str, Any]:
    """Execute query against vmalert API."""
    return kubectl_curl(f"{VMALERT_URL}{endpoint}")


def query_vmsingle(query: str) -> dict[str, Any]:
    """Execute PromQL query against VictoriaMetrics."""
    encoded_query = quote(query)
    return kubectl_curl(f"{VMSINGLE_URL}/api/v1/query?query={encoded_query}")


def colorize(text: str, color: str) -> str:
    """Wrap text in ANSI color codes."""
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


def format_labels(labels: dict[str, str], exclude: set[str] | None = None) -> list[str]:
    """Format labels as key=value pairs, excluding specified keys."""
    exclude = exclude or set()
    return [f"{k}={v}" for k, v in labels.items() if k not in exclude]


def list_alerts(states: list[str] | None = None) -> None:
    """List alerts filtered by state with formatted output."""
    states = states or ["firing", "pending"]
    state_desc = " and ".join(states)
    print(colorize(f"Querying vmalert for {state_desc} alerts...\n", "blue"))

    data = query_vmalert("/api/v1/alerts")
    alerts = data.get("data", {}).get("alerts", [])

    filtered_alerts = [
        a
        for a in alerts
        if a.get("state") in states
        and a.get("labels", {}).get("alertname") not in IGNORED_ALERTS
    ]

    if not filtered_alerts:
        print(colorize(f"No alerts in {state_desc} state", "green"))
        return

    for alert in filtered_alerts:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        severity = labels.get("severity", "none")
        color = SEVERITY_COLORS.get(severity, "reset")

        print(
            colorize(f"[{severity}]", color),
            f"{labels.get('alertname', 'Unknown')} ({alert.get('state', 'unknown')})",
        )
        print(f"  {annotations.get('summary', annotations.get('description', 'No description'))}")
        print(f"  Expression: {alert.get('expression', 'N/A')}")

        relevant_labels = format_labels(
            labels, exclude={"alertname", "alertgroup", "prometheus", "severity"}
        )
        if relevant_labels:
            print("  Key labels:")
            for label in relevant_labels[:5]:
                print(f"    {label}")

        print(
            colorize("  Details:", "blue"),
            f"./scripts/vmalert-query.py detail {labels.get('alertname')}",
        )
        print()


def detail_alert(alert_name: str) -> None:
    """Show detailed information for a specific alert."""
    print(colorize(f"Querying vmalert for alert: {alert_name}\n", "blue"))

    data = query_vmalert("/api/v1/alerts")
    alerts = [
        a
        for a in data.get("data", {}).get("alerts", [])
        if a.get("labels", {}).get("alertname") == alert_name
    ]

    if not alerts:
        print(colorize(f"No alert found with name: {alert_name}", "red"))
        sys.exit(1)

    alert = alerts[0]
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})

    print(f"Alert: {labels.get('alertname', 'Unknown')}")
    print(f"State: {alert.get('state', 'unknown')}")
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
    print(f"\nAlert Source: {alert.get('source', 'N/A')}")


def list_rules() -> None:
    """List all alert rules and their status."""
    print(colorize("Querying vmalert for rule groups...\n", "blue"))

    data = query_vmalert("/api/v1/rules")
    groups = data.get("data", {}).get("groups", [])

    for group in groups:
        print(f"Group: {group.get('name', 'Unknown')}")
        print(f"Interval: {group.get('interval', 'N/A')}")
        print("Rules:")
        for rule in group.get("rules", []):
            print(
                f"  - {rule.get('name', 'Unknown')} ({rule.get('type', 'unknown')}) - {rule.get('state', 'unknown')}"
            )
        print()


def json_output(state: str = "all") -> None:
    """Output raw JSON optionally filtered by state."""
    data = query_vmalert("/api/v1/alerts")
    alerts = data.get("data", {}).get("alerts", [])

    if state != "all":
        alerts = [a for a in alerts if a.get("state") == state]

    print(json.dumps(alerts, indent=2))


def alert_history(duration: str, alert_name: str | None = None) -> None:
    """Show historical alert firing frequency over specified duration."""
    title = f"Querying alert history for last {duration}"
    if alert_name:
        title += f" (filtered by {alert_name})"
    print(colorize(f"{title}...\n", "blue"))

    # Build query with optional alert name filter
    if alert_name:
        query = f'sum(changes(ALERTS{{alertstate="firing",alertname="{alert_name}"}}[{duration}])) by (alertname,severity,instance,namespace,job,pod,node)'
    else:
        query = f"topk(20, sum(changes(ALERTS{{alertstate=\"firing\"}}[{duration}])) by (alertname,severity))"

    data = query_vmsingle(query)
    results = data.get("data", {}).get("result", [])

    if not results:
        filter_msg = f" for alert '{alert_name}'" if alert_name else ""
        print(colorize(f"No alerts fired in last {duration}{filter_msg}", "green"))
        return

    # Sort by firing count descending
    results.sort(key=lambda x: float(x["value"][1]), reverse=True)

    if alert_name:
        # Detailed view with all labels when filtering by alert name
        for result in results:
            metric = result["metric"]
            count = int(float(result["value"][1]))

            if count == 0:
                continue

            alertname = metric.get("alertname", "Unknown")
            severity = metric.get("severity", "none")
            color = SEVERITY_COLORS.get(severity, "reset")

            print(colorize(f"[{severity}]", color), f"{alertname} - Fired {count} times")

            # Show relevant labels
            relevant_labels = format_labels(metric, exclude={"alertname", "severity", "__name__"})
            if relevant_labels:
                print("  Labels:")
                for label in relevant_labels:
                    print(f"    {label}")
            print()
    else:
        # Summary view when showing all alerts
        print(f"{'Alert Name':<45} {'Severity':<12} {'Fired Count'}")
        print("-" * 70)

        for result in results:
            metric = result["metric"]
            alertname = metric.get("alertname", "Unknown")
            severity = metric.get("severity", "none")
            count = int(float(result["value"][1]))

            if count == 0:
                continue

            color = SEVERITY_COLORS.get(severity, "reset")
            severity_colored = colorize(f"{severity:<12}", color)
            print(f"{alertname:<45} {severity_colored} {count}")


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Query vmalert for alert information")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("firing", help="List only firing alerts")
    subparsers.add_parser("pending", help="List only pending alerts")
    subparsers.add_parser("inactive", help="List only inactive alerts")

    detail_parser = subparsers.add_parser("detail", help="Show detailed information for an alert")
    detail_parser.add_argument("name", help="Alert name")

    subparsers.add_parser("rules", help="Show all alert rules and their status")

    json_parser = subparsers.add_parser("json", help="Output raw JSON")
    json_parser.add_argument("state", nargs="?", default="all", help="Filter by state")

    history_parser = subparsers.add_parser(
        "history", help="Show historical alert firing frequency (e.g., 5m, 1h, 6h, 24h)"
    )
    history_parser.add_argument(
        "duration", nargs="?", default="6h", help="Time duration (default: 6h)"
    )
    history_parser.add_argument(
        "--alert", "-a", help="Filter history by specific alert name"
    )

    args = parser.parse_args()
    command = args.command

    try:
        if command is None:
            list_alerts()
        elif command == "firing":
            list_alerts(["firing"])
        elif command == "pending":
            list_alerts(["pending"])
        elif command == "inactive":
            list_alerts(["inactive"])
        elif command == "detail":
            detail_alert(args.name)
        elif command == "rules":
            list_rules()
        elif command == "json":
            json_output(args.state)
        elif command == "history":
            alert_history(args.duration, args.alert)
    except subprocess.CalledProcessError as e:
        print(f"Error querying vmalert: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON response: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
