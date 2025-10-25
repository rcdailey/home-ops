#!/usr/bin/env python3

"""Query VictoriaMetrics for container resource metrics via kubectl."""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

VMSINGLE_URL = "http://vmsingle-victoria-metrics-k8s-stack.observability:8428"

COLORS = {
    "blue": "\033[0;34m",
    "green": "\033[0;32m",
    "yellow": "\033[1;33m",
    "red": "\033[0;31m",
    "reset": "\033[0m",
}


def colorize(text: str, color: str) -> str:
    """Wrap text in ANSI color codes."""
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


def kubectl_curl(url: str) -> dict[str, Any]:
    """Execute curl via rook-ceph-tools pod."""
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


def query_vmsingle(query: str) -> dict[str, Any]:
    """Execute PromQL query against VictoriaMetrics."""
    encoded_query = quote(query)
    return kubectl_curl(f"{VMSINGLE_URL}/api/v1/query?query={encoded_query}")


def parse_duration(duration: str) -> int:
    """Convert duration string (e.g., '7d', '24h', '30m') to seconds."""
    unit = duration[-1]
    value = int(duration[:-1])

    if unit == 'd':
        return value * 86400
    elif unit == 'h':
        return value * 3600
    elif unit == 'm':
        return value * 60
    else:
        raise ValueError(f"Invalid duration unit: {unit}. Use d (days), h (hours), or m (minutes)")


def format_cpu_cores(value: float) -> str:
    """Format CPU value as millicores or cores."""
    if value < 0.001:
        return f"{value * 1000000:.0f}µ"
    elif value < 1:
        return f"{value * 1000:.0f}m"
    else:
        return f"{value:.2f}"


def format_memory_bytes(value: float) -> str:
    """Format memory value in human-readable format."""
    for unit in ['B', 'Ki', 'Mi', 'Gi', 'Ti']:
        if value < 1024.0:
            return f"{value:.1f}{unit}"
        value /= 1024.0
    return f"{value:.1f}Pi"


def cpu_usage(namespace: str, pod_pattern: str, container: str, duration: str) -> None:
    """Query CPU usage statistics for a container."""
    print(colorize(f"Querying CPU usage for {namespace}/{pod_pattern}/{container} over {duration}...\n", "blue"))

    # Base selector
    selector = f'namespace="{namespace}",pod=~"{pod_pattern}",container="{container}"'

    # Current usage
    current_query = f"rate(container_cpu_usage_seconds_total{{{selector}}}[5m])"
    current_data = query_vmsingle(current_query)
    current_results = current_data.get("data", {}).get("result", [])

    if current_results:
        current_value = float(current_results[0]["value"][1])
        print(f"Current (5m rate): {format_cpu_cores(current_value)} cores")
    else:
        print("Current: No data")

    # Max over duration (take max across all series)
    max_query = f"max_over_time(rate(container_cpu_usage_seconds_total{{{selector}}}[5m])[{duration}:])"
    max_data = query_vmsingle(max_query)
    max_results = max_data.get("data", {}).get("result", [])

    if max_results:
        max_value = max(float(r["value"][1]) for r in max_results)
        print(f"Max ({duration}):     {format_cpu_cores(max_value)} cores")
    else:
        print(f"Max ({duration}):     No data")

    # Average over duration (average across all series)
    avg_query = f"avg_over_time(rate(container_cpu_usage_seconds_total{{{selector}}}[5m])[{duration}:])"
    avg_data = query_vmsingle(avg_query)
    avg_results = avg_data.get("data", {}).get("result", [])

    if avg_results:
        # Take average of averages across all series
        avg_value = sum(float(r["value"][1]) for r in avg_results) / len(avg_results)
        print(f"Avg ({duration}):     {format_cpu_cores(avg_value)} cores")
    else:
        print(f"Avg ({duration}):     No data")

    # CPU throttling
    throttle_query = f"""
    (
      sum(increase(container_cpu_cfs_throttled_periods_total{{{selector}}}[{duration}]))
      /
      sum(increase(container_cpu_cfs_periods_total{{{selector}}}[{duration}]))
    ) * 100
    """
    throttle_data = query_vmsingle(throttle_query)
    throttle_results = throttle_data.get("data", {}).get("result", [])

    if throttle_results:
        throttle_pct = float(throttle_results[0]["value"][1])
        color = "red" if throttle_pct > 25 else "yellow" if throttle_pct > 10 else "green"
        print(f"Throttled ({duration}): " + colorize(f"{throttle_pct:.2f}%", color))
    else:
        print(f"Throttled ({duration}): No data")


def memory_usage(namespace: str, pod_pattern: str, container: str, duration: str) -> None:
    """Query memory usage statistics for a container."""
    print(colorize(f"Querying memory usage for {namespace}/{pod_pattern}/{container} over {duration}...\n", "blue"))

    # Base selector
    selector = f'namespace="{namespace}",pod=~"{pod_pattern}",container="{container}"'

    # Current usage
    current_query = f"container_memory_working_set_bytes{{{selector}}}"
    current_data = query_vmsingle(current_query)
    current_results = current_data.get("data", {}).get("result", [])

    if current_results:
        current_value = float(current_results[0]["value"][1])
        print(f"Current: {format_memory_bytes(current_value)}")
    else:
        print("Current: No data")

    # Max over duration (take max across all series)
    max_query = f"max_over_time(container_memory_working_set_bytes{{{selector}}}[{duration}:])"
    max_data = query_vmsingle(max_query)
    max_results = max_data.get("data", {}).get("result", [])

    if max_results:
        max_value = max(float(r["value"][1]) for r in max_results)
        print(f"Max ({duration}): {format_memory_bytes(max_value)}")
    else:
        print(f"Max ({duration}): No data")

    # Average over duration (average across all series)
    avg_query = f"avg_over_time(container_memory_working_set_bytes{{{selector}}}[{duration}:])"
    avg_data = query_vmsingle(avg_query)
    avg_results = avg_data.get("data", {}).get("result", [])

    if avg_results:
        # Take average of averages across all series
        avg_value = sum(float(r["value"][1]) for r in avg_results) / len(avg_results)
        print(f"Avg ({duration}): {format_memory_bytes(avg_value)}")
    else:
        print(f"Avg ({duration}): No data")


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Query VictoriaMetrics for container resource metrics",
        epilog="Examples:\n"
        "  %(prog)s cpu media 'plex.*' vector-sidecar 7d\n"
        "  %(prog)s memory default 'homepage.*' app 24h\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="metric", help="Metric type to query", required=True)

    # CPU subcommand
    cpu_parser = subparsers.add_parser("cpu", help="Query CPU usage and throttling")
    cpu_parser.add_argument("namespace", help="Namespace name")
    cpu_parser.add_argument("pod", help="Pod name or pattern (regex)")
    cpu_parser.add_argument("container", help="Container name")
    cpu_parser.add_argument("duration", nargs="?", default="7d", help="Duration (e.g., 7d, 24h, 30m)")

    # Memory subcommand
    mem_parser = subparsers.add_parser("memory", help="Query memory usage")
    mem_parser.add_argument("namespace", help="Namespace name")
    mem_parser.add_argument("pod", help="Pod name or pattern (regex)")
    mem_parser.add_argument("container", help="Container name")
    mem_parser.add_argument("duration", nargs="?", default="7d", help="Duration (e.g., 7d, 24h, 30m)")

    args = parser.parse_args()

    try:
        if args.metric == "cpu":
            cpu_usage(args.namespace, args.pod, args.container, args.duration)
        elif args.metric == "memory":
            memory_usage(args.namespace, args.pod, args.container, args.duration)
    except subprocess.CalledProcessError as e:
        print(colorize(f"Error querying VictoriaMetrics: {e}", "red"), file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(colorize(f"Error parsing JSON response: {e}", "red"), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(colorize(f"Unexpected error: {e}", "red"), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
