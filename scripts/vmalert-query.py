#!/usr/bin/env python3

"""Query vmalert for alert information via ephemeral kubectl pods."""

import argparse
import json
import subprocess
import sys
from typing import Any

VMALERT_URL = "http://vmalert-victoria-metrics-k8s-stack.observability:8080"
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


def query_vmalert(endpoint: str) -> dict[str, Any]:
    """Execute query against vmalert API via ephemeral kubectl pod."""
    cmd = [
        "kubectl",
        "run",
        f"vmalert-query-{subprocess.os.getpid()}",
        "--rm",
        "-i",
        "--quiet",
        f"--image={CURL_IMAGE}",
        "--restart=Never",
        "--",
        "curl",
        "-s",
        f"{VMALERT_URL}{endpoint}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def colorize(text: str, color: str) -> str:
    """Wrap text in ANSI color codes."""
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


def format_labels(labels: dict[str, str], exclude: set[str] | None = None) -> list[str]:
    """Format labels as key=value pairs, excluding specified keys."""
    exclude = exclude or set()
    return [f"{k}={v}" for k, v in labels.items() if k not in exclude]


def list_alerts(state: str = "firing") -> None:
    """List alerts filtered by state with formatted output."""
    print(colorize(f"Querying vmalert for {state} alerts...\n", "blue"))

    data = query_vmalert("/api/v1/alerts")
    alerts = data.get("data", {}).get("alerts", [])

    if state != "all":
        alerts = [a for a in alerts if a.get("state") == state]

    if not alerts:
        print(colorize(f"No alerts in {state} state", "green"))
        return

    for alert in alerts:
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


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Query vmalert for alert information")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("firing", help="List all firing alerts (default)")
    subparsers.add_parser("pending", help="List all pending alerts")
    subparsers.add_parser("inactive", help="List all inactive alerts")
    subparsers.add_parser("all", help="List all alerts regardless of state")

    detail_parser = subparsers.add_parser("detail", help="Show detailed information for an alert")
    detail_parser.add_argument("name", help="Alert name")

    subparsers.add_parser("rules", help="Show all alert rules and their status")

    json_parser = subparsers.add_parser("json", help="Output raw JSON")
    json_parser.add_argument("state", nargs="?", default="all", help="Filter by state")

    args = parser.parse_args()
    command = args.command or "firing"

    try:
        if command in ("firing", "pending", "inactive", "all"):
            list_alerts(command)
        elif command == "detail":
            detail_alert(args.name)
        elif command == "rules":
            list_rules()
        elif command == "json":
            json_output(args.state)
    except subprocess.CalledProcessError as e:
        print(f"Error querying vmalert: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON response: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
