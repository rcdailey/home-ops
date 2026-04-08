#!/usr/bin/env python3

"""Query VictoriaMetrics and vmalert for metrics and alerts.

Examples:
  # Container metrics (default --from 7d)
  %(prog)s cpu media 'plex.*' plex
  %(prog)s memory default 'homepage.*' app --from 24h

  # Raw PromQL queries
  %(prog)s query 'up{job="kubelet"}'
  %(prog)s query 'rate(http_requests_total[5m])' --from 24h --step 5m

  # Point-in-time investigation (--at interprets as local time)
  %(prog)s query 'etcd_server_is_leader' --at 2026-04-09T16:19:45
  %(prog)s query 'some_metric' --at 2026-04-09T16:19:45 --window 20m --step 30s

  # Sparse metrics (hide all-zero series)
  %(prog)s query 'ceph_pg_scrubbing' --from 1h --hide-zero

  # Discovery
  %(prog)s labels                    # List all label names
  %(prog)s labels namespace          # List values for 'namespace' label
  %(prog)s metrics --filter cpu      # Find CPU-related metrics

  # Alerts (current state from vmalert)
  %(prog)s alerts                    # List firing alerts
  %(prog)s alerts --state all        # List all alert states
  %(prog)s alert Watchdog            # Alert details

  # Alerts (historical from VictoriaMetrics)
  %(prog)s alerts --from 24h         # Alerts that fired in last 24h
  %(prog)s alert PodNotReady --from 24h  # Historical alert details
"""

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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

SEVERITY_COLORS = {
    "critical": "red",
    "warning": "yellow",
    "info": "blue",
    "none": "blue",
}
IGNORED_ALERTS = {"Watchdog", "InfoInhibitor"}
IGNORED_ALERT_PREFIXES = ("Unifi",)


def is_ignored_alert(alertname: str) -> bool:
    """Check if alert should be ignored."""
    if alertname in IGNORED_ALERTS:
        return True
    return alertname.startswith(IGNORED_ALERT_PREFIXES)


# Global JSON output mode
_json_mode = False


@dataclass
class TimeRange:
    """Unified time range handling for all query types.

    Attributes:
        start: Start time as duration (e.g., "24h", "7d") or ISO timestamp.
               None means current/instant mode.
        end: End time as duration or ISO timestamp. None means "now".
    """

    start: str | None = None
    end: str | None = None

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "TimeRange":
        """Create TimeRange from parsed arguments.

        Supports --at for point-in-time investigation, which expands to a
        symmetric window around the given timestamp (default 10 minutes).
        """
        at = getattr(args, "time_at", None)
        if at:
            window = getattr(args, "window", "10m")
            half_sec = cls._duration_to_seconds(window) // 2
            at_dt = datetime.fromisoformat(at)
            if at_dt.tzinfo is None:
                at_dt = at_dt.astimezone()  # Treat naive as local time
            at_utc = at_dt.astimezone(timezone.utc)
            start_dt = at_utc - timedelta(seconds=half_sec)
            end_dt = at_utc + timedelta(seconds=half_sec)
            # VictoriaMetrics interprets naive timestamps as UTC
            fmt = "%Y-%m-%dT%H:%M:%S"
            return cls(
                start=start_dt.strftime(fmt),
                end=end_dt.strftime(fmt),
            )
        return cls(
            start=getattr(args, "time_from", None),
            end=getattr(args, "time_to", None),
        )

    def is_current(self) -> bool:
        """Check if this represents current/instant mode (no time range)."""
        return self.start is None

    def to_duration(self) -> str:
        """Convert start to PromQL duration format.

        Returns the duration string as-is if it's a duration (e.g., "24h"),
        or calculates the duration from an ISO timestamp.
        """
        if self.start is None:
            raise ValueError("Cannot convert None start to duration")

        if self._is_duration(self.start):
            return self.start

        # ISO timestamp: calculate duration from now
        start_dt = datetime.fromisoformat(self.start.replace("Z", "+00:00"))
        end_dt = self._parse_end_time()
        delta = end_dt - start_dt
        return f"{int(delta.total_seconds())}s"

    def to_promql_range(self) -> str:
        """Return PromQL range selector like '[24h]'."""
        return f"[{self.to_duration()}]"

    def to_range_params(self, step: str = "1m") -> dict[str, str]:
        """Convert to VictoriaMetrics query_range API parameters."""
        params: dict[str, str] = {"step": step}

        if self.start:
            if self._is_duration(self.start):
                params["start"] = f"-{self.start}"
            else:
                params["start"] = self.start

        if self.end:
            if self._is_duration(self.end):
                params["end"] = f"-{self.end}"
            else:
                params["end"] = self.end

        return params

    def _parse_end_time(self) -> datetime:
        """Parse end time, defaulting to now."""
        if self.end is None:
            return datetime.now(timezone.utc)
        if self._is_duration(self.end):
            # Duration means "X ago from now"
            seconds = self._duration_to_seconds(self.end)
            now = datetime.now(timezone.utc).replace(microsecond=0)
            return now - timedelta(seconds=seconds)
        return datetime.fromisoformat(self.end.replace("Z", "+00:00"))

    @staticmethod
    def _is_duration(value: str) -> bool:
        """Check if value is a duration string (e.g., '24h', '7d', '30m')."""
        return bool(re.match(r"^\d+[smhdw]$", value))

    @staticmethod
    def _duration_to_seconds(duration: str) -> int:
        """Convert duration string to seconds."""
        unit = duration[-1]
        value = int(duration[:-1])
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
        return value * multipliers.get(unit, 1)


def add_time_args(
    parser: argparse.ArgumentParser,
    default_start: str | None = None,
    support_at: bool = False,
) -> None:
    """Add standard --from/--to time range arguments to a parser.

    Args:
        parser: The argument parser to add arguments to.
        default_start: Default value for --from. None means current/instant mode.
        support_at: If True, add --at and --window for point-in-time investigation.
    """
    parser.add_argument(
        "--from",
        dest="time_from",
        default=default_start,
        metavar="TIME",
        help="Start time (duration like 24h/7d, or ISO timestamp)",
    )
    parser.add_argument(
        "--to",
        dest="time_to",
        metavar="TIME",
        help="End time (default: now)",
    )
    if support_at:
        parser.add_argument(
            "--at",
            dest="time_at",
            metavar="TIMESTAMP",
            help="Investigate around a specific time (ISO timestamp); expands to symmetric window",
        )
        parser.add_argument(
            "--window",
            default="10m",
            metavar="DURATION",
            help="Window size for --at (default: 10m)",
        )


def colorize(text: str, color: str) -> str:
    """Wrap text in ANSI color codes."""
    if _json_mode:
        return text
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


def kubectl_curl(url: str) -> dict[str, Any]:
    """Execute curl via rook-ceph-tools deployment."""
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


def query_vm(endpoint: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    """Query VictoriaMetrics API."""
    url = f"{VMSINGLE_URL}{endpoint}"
    if params:
        url = f"{url}?{urlencode(params)}"
    return kubectl_curl(url)


def query_vmalert(endpoint: str) -> dict[str, Any]:
    """Query vmalert API."""
    return kubectl_curl(f"{VMALERT_URL}{endpoint}")


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


def format_timestamp(ts: float, local: bool = False) -> str:
    """Format Unix timestamp as human-readable string.

    Args:
        ts: Unix timestamp.
        local: If True, display in local time without timezone suffix.
    """
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if local:
        dt = dt.astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# Labels that are always noise in investigation output
_NOISE_LABELS = frozenset(
    {
        "__name__",
        "container",
        "endpoint",
        "job",
        "namespace",
        "pod",
        "prometheus",
        "service",
    }
)

# Labels to drop when a better human-readable equivalent exists
_REDUNDANT_LABEL_PAIRS = {
    "instance": "nodename",  # drop instance when nodename present
}


def compact_labels(metric: dict[str, str]) -> str:
    """Format metric labels, omitting noise and redundant labels.

    Drops common infrastructure labels, and prefers human-readable names
    (e.g., nodename over instance). Returns just the value when only one
    distinguishing label remains.
    """
    interesting = {k: v for k, v in metric.items() if k not in _NOISE_LABELS}
    # Drop redundant labels when their readable equivalent exists
    for drop_key, keep_key in _REDUNDANT_LABEL_PAIRS.items():
        if drop_key in interesting and keep_key in interesting:
            del interesting[drop_key]
    if not interesting:
        # Fall back to full labels if everything was noise
        interesting = {k: v for k, v in metric.items() if k != "__name__"}
    if len(interesting) == 1:
        return next(iter(interesting.values()))
    return ", ".join(f"{k}={v}" for k, v in interesting.items())


def format_value(val: str) -> str:
    """Format a numeric value string for readable output.

    Reduces excessive decimal precision while preserving meaningful digits.
    Integer-valued floats display as integers. Small values keep enough
    precision to be meaningful.
    """
    try:
        f = float(val)
    except (ValueError, TypeError):
        return val
    if f != f:  # NaN
        return "NaN"
    if abs(f) == float("inf"):
        return val
    # Integer-valued
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    # Adaptive precision: more digits for small numbers
    abs_f = abs(f)
    if abs_f >= 100:
        return f"{f:.1f}"
    if abs_f >= 1:
        return f"{f:.3f}"
    if abs_f >= 0.001:
        return f"{f:.4f}"
    return f"{f:.6f}"


def container_stats(
    namespace: str,
    pod: str,
    container: str,
    time_range: TimeRange,
    metric: str,
    rate: str | None = None,
) -> dict[str, float | None]:
    """Query current/max/avg for a container metric."""
    duration = time_range.to_duration()
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
    time_range = TimeRange.from_args(args)
    duration = time_range.to_duration()

    if not _json_mode:
        print(
            colorize(
                f"Querying CPU for {args.namespace}/{args.pod}/{args.container}...\n",
                "blue",
            )
        )

    stats = container_stats(
        args.namespace,
        args.pod,
        args.container,
        time_range,
        "container_cpu_usage_seconds_total",
        rate="5m",
    )

    # CPU throttling
    selector = (
        f'namespace="{args.namespace}",pod=~"{args.pod}",container="{args.container}"'
    )
    throttle_query = f"""
    (sum(increase(container_cpu_cfs_throttled_periods_total{{{selector}}}[{duration}]))
     / sum(increase(container_cpu_cfs_periods_total{{{selector}}}[{duration}]))) * 100
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
        print(f"Max ({duration}):     {format_cpu(stats['max'])} cores")
    if stats["avg"] is not None:
        print(f"Avg ({duration}):     {format_cpu(stats['avg'])} cores")
    if throttle_pct is not None:
        color = (
            "red" if throttle_pct > 25 else "yellow" if throttle_pct > 10 else "green"
        )
        print(f"Throttled ({duration}): " + colorize(f"{throttle_pct:.2f}%", color))


def cmd_memory(args: argparse.Namespace) -> None:
    """Query memory usage statistics."""
    time_range = TimeRange.from_args(args)
    duration = time_range.to_duration()

    if not _json_mode:
        print(
            colorize(
                f"Querying memory for {args.namespace}/{args.pod}/{args.container}...\n",
                "blue",
            )
        )

    stats = container_stats(
        args.namespace,
        args.pod,
        args.container,
        time_range,
        "container_memory_working_set_bytes",
    )

    if _json_mode:
        print(json.dumps({"memory": stats}, indent=2))
        return

    if stats["current"] is not None:
        print(f"Current: {format_memory(stats['current'])}")
    else:
        print("Current: No data")
    if stats["max"] is not None:
        print(f"Max ({duration}): {format_memory(stats['max'])}")
    if stats["avg"] is not None:
        print(f"Avg ({duration}): {format_memory(stats['avg'])}")


def cmd_query(args: argparse.Namespace) -> None:
    """Execute raw PromQL query."""
    time_range = TimeRange.from_args(args)

    if time_range.is_current():
        data = query_vm("/api/v1/query", {"query": args.promql})
    else:
        params = {"query": args.promql, **time_range.to_range_params(args.step)}
        data = query_vm("/api/v1/query_range", params)

    if _json_mode:
        print(json.dumps(data, indent=2))
        return

    results = data.get("data", {}).get("result", [])
    result_type = data.get("data", {}).get("resultType", "unknown")

    if not results:
        print(colorize("No results", "yellow"))
        return

    hide_zero = getattr(args, "hide_zero", False)
    if hide_zero and result_type == "matrix":
        original_count = len(results)
        results = [
            r for r in results if any(float(val) != 0 for _, val in r.get("values", []))
        ]
        hidden = original_count - len(results)
        suffix = f" ({hidden} all-zero series hidden)" if hidden else ""
        if not results:
            print(
                colorize(
                    f"No results (all {original_count} series were zero)", "yellow"
                )
            )
            return
    else:
        suffix = ""

    print(
        colorize(f"Result type: {result_type}, {len(results)} series{suffix}\n", "blue")
    )

    max_series = 20

    if result_type == "matrix":
        _print_matrix(results[:max_series])
    else:
        for r in results[:max_series]:
            metric = r.get("metric", {})
            labels = compact_labels(metric)
            value = r.get("value", [None, "N/A"])
            print(f"{{{labels}}} => {format_value(value[1])}")

    if len(results) > max_series:
        print(colorize(f"\n... {len(results) - max_series} more series", "yellow"))


def _print_matrix(results: list[dict[str, Any]]) -> None:
    """Print matrix results in a compact columnar format.

    Prints the date once as a header, then uses time-only columns.
    Each series gets one row with its label and aligned values.
    """
    if not results:
        return

    max_points = 50

    # Collect all timestamps across series (use first series as reference)
    all_values = results[0].get("values", [])
    if not all_values:
        return

    timestamps = [float(ts) for ts, _ in all_values[:max_points]]
    if not timestamps:
        return

    # Build time headers, printing date only when it changes
    prev_date = ""
    time_headers: list[str] = []
    date_header = ""
    for ts in timestamps:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M:%S")
        if date_str != prev_date:
            date_header = date_str
            prev_date = date_str
        time_headers.append(time_str)

    # Build compact labels for each series
    series_labels: list[str] = []
    for r in results:
        series_labels.append(compact_labels(r.get("metric", {})))

    # Calculate column width from values (find widest formatted value)
    col_width = 8  # minimum width for HH:MM:SS
    for r in results:
        for _, val in r.get("values", [])[:max_points]:
            col_width = max(col_width, len(format_value(val)))
    col_width += 1  # padding

    label_width = max(len(lb) for lb in series_labels) if series_labels else 0
    label_width = max(label_width, 5)  # minimum

    # Print date header
    print(colorize(f"Date: {date_header}", "blue"))

    # Print time header row
    header = " " * label_width + " | "
    header += " ".join(h.rjust(col_width) for h in time_headers)
    print(header)

    # Print separator
    print("-" * len(header))

    # Print each series as one row
    for i, r in enumerate(results):
        values = r.get("values", [])
        # Build a lookup from timestamp to value
        val_map = {float(ts): val for ts, val in values[:max_points]}
        row = series_labels[i].ljust(label_width) + " | "
        row += " ".join(
            format_value(val_map.get(ts, "")).rjust(col_width) for ts in timestamps
        )
        print(row)

    total_points = len(results[0].get("values", []))
    if total_points > max_points:
        print(f"... ({total_points} total points, showing first {max_points})")


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
    """List alerts - current state or historical."""
    time_range = TimeRange.from_args(args)

    if time_range.is_current():
        _cmd_alerts_current(args)
    else:
        _cmd_alerts_historical(args, time_range)


def _cmd_alerts_current(args: argparse.Namespace) -> None:
    """List current alerts from vmalert."""
    data = query_vmalert("/api/v1/alerts")
    alerts = data.get("data", {}).get("alerts", [])

    states = ["firing", "pending", "inactive"] if args.state == "all" else [args.state]
    filtered = [
        a
        for a in alerts
        if a.get("state") in states
        and not is_ignored_alert(a.get("labels", {}).get("alertname", ""))
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

        print(
            colorize(f"[{severity}]", color),
            f"{labels.get('alertname')} ({alert.get('state')})",
        )
        print(
            f"  {annotations.get('summary', annotations.get('description', 'No description'))}"
        )
        print(f"  Expression: {alert.get('expression', 'N/A')}")

        relevant = format_labels(
            labels, exclude={"alertname", "alertgroup", "prometheus", "severity"}
        )
        if relevant:
            print("  Labels:", ", ".join(relevant[:5]))
        print()


def _cmd_alerts_historical(args: argparse.Namespace, time_range: TimeRange) -> None:
    """List historical alerts from VictoriaMetrics."""
    duration = time_range.to_duration()

    if not _json_mode:
        print(colorize(f"Alerts fired in last {duration}...\n", "blue"))

    query = f'topk(20, sum(changes(ALERTS{{alertstate="firing"}}[{duration}])) by (alertname,severity))'
    data = query_vm("/api/v1/query", {"query": query})
    results = data.get("data", {}).get("result", [])

    if _json_mode:
        print(json.dumps(results, indent=2))
        return

    if not results:
        print(colorize(f"No alerts fired in last {duration}", "green"))
        return

    results.sort(key=lambda x: float(x["value"][1]), reverse=True)

    for r in results:
        metric = r["metric"]
        count = int(float(r["value"][1]))
        if count == 0:
            continue

        alertname = metric.get("alertname", "unknown")
        if is_ignored_alert(alertname):
            continue

        severity = metric.get("severity", "none")
        color = SEVERITY_COLORS.get(severity, "reset")
        print(colorize(f"[{severity}]", color), f"{alertname} - Fired {count} times")


def cmd_alert(args: argparse.Namespace) -> None:
    """Show detailed alert information - current or historical."""
    time_range = TimeRange.from_args(args)

    if time_range.is_current():
        _cmd_alert_current(args)
    else:
        _cmd_alert_historical(args, time_range)


def _cmd_alert_current(args: argparse.Namespace) -> None:
    """Show current alert details from vmalert."""
    data = query_vmalert("/api/v1/alerts")
    alerts = [
        a
        for a in data.get("data", {}).get("alerts", [])
        if a.get("labels", {}).get("alertname") == args.name
    ]

    if not alerts:
        print(colorize(f"No active alert found: {args.name}", "red"), file=sys.stderr)
        print(
            colorize(
                "Hint: Use --from <duration> to search historical alerts", "yellow"
            ),
            file=sys.stderr,
        )
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


def _cmd_alert_historical(args: argparse.Namespace, time_range: TimeRange) -> None:
    """Show historical alert details from VictoriaMetrics."""
    duration = time_range.to_duration()
    alertname = args.name

    if not _json_mode:
        print(
            colorize(f"Historical data for {alertname} (last {duration})...\n", "blue")
        )

    # Query the ALERTS metric for this specific alert
    query = f'ALERTS{{alertname="{alertname}",alertstate="firing"}}'
    params = time_range.to_range_params(step="1m")
    params["query"] = query

    data = query_vm("/api/v1/query_range", params)
    results = data.get("data", {}).get("result", [])

    if _json_mode:
        print(
            json.dumps(
                {"alertname": alertname, "duration": duration, "instances": results},
                indent=2,
            )
        )
        return

    if not results:
        print(
            colorize(f"No firing instances of {alertname} in last {duration}", "yellow")
        )
        return

    print(f"Alert: {alertname} (historical)")
    print(f"Period: last {duration}")
    print(f"Instances: {len(results)}")

    for i, r in enumerate(results):
        labels = r.get("metric", {})
        values = r.get("values", [])

        if not values:
            continue

        # Find firing periods (value == 1)
        firing_periods = _extract_firing_periods(values)

        print(f"\nInstance {i + 1}:")
        severity = labels.get("severity", "none")
        print(f"  Severity: {severity}")

        relevant = format_labels(
            labels, exclude={"alertname", "alertstate", "__name__", "severity"}
        )
        if relevant:
            print("  Labels:")
            for label in relevant:
                print(f"    {label}")

        if firing_periods:
            print("  Firing periods:")
            for start_ts, end_ts in firing_periods:
                print(f"    {format_timestamp(start_ts)} - {format_timestamp(end_ts)}")


def _extract_firing_periods(values: list[list]) -> list[tuple[float, float]]:
    """Extract contiguous firing periods from time series values.

    Args:
        values: List of [timestamp, value] pairs from query_range.

    Returns:
        List of (start_timestamp, end_timestamp) tuples for firing periods.
    """
    periods = []
    start_ts = None

    for ts, val in values:
        is_firing = float(val) == 1

        if is_firing and start_ts is None:
            start_ts = float(ts)
        elif not is_firing and start_ts is not None:
            periods.append((start_ts, float(ts)))
            start_ts = None

    # Handle case where alert is still firing at end of range
    if start_ts is not None and values:
        periods.append((start_ts, float(values[-1][0])))

    return periods


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
    add_time_args(p, default_start="7d")

    # memory
    p = subparsers.add_parser("memory", help="Memory usage")
    p.add_argument("namespace", help="Namespace")
    p.add_argument("pod", help="Pod name pattern (regex)")
    p.add_argument("container", help="Container name")
    add_time_args(p, default_start="7d")

    # query
    p = subparsers.add_parser("query", help="Raw PromQL query")
    p.add_argument("promql", help="PromQL expression")
    p.add_argument(
        "--step", default="1m", help="Step interval for range queries (default: 1m)"
    )
    p.add_argument(
        "--hide-zero",
        action="store_true",
        help="Hide series where all values are zero (useful for sparse metrics)",
    )
    add_time_args(p, support_at=True)

    # labels
    p = subparsers.add_parser("labels", help="List labels or label values")
    p.add_argument("name", nargs="?", help="Label name (omit to list all labels)")

    # metrics
    p = subparsers.add_parser("metrics", help="List metric names")
    p.add_argument("--filter", "-f", help="Filter pattern (case-insensitive)")

    # alerts
    p = subparsers.add_parser(
        "alerts", help="List alerts (current or historical with --from)"
    )
    p.add_argument(
        "--state",
        "-s",
        default="firing",
        choices=["firing", "pending", "inactive", "all"],
        help="Filter by state (current mode only)",
    )
    add_time_args(p)

    # alert
    p = subparsers.add_parser(
        "alert", help="Alert details (current or historical with --from)"
    )
    p.add_argument("name", help="Alert name")
    add_time_args(p)

    # rules
    subparsers.add_parser("rules", help="List alert rules")

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
