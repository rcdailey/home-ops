"""VictoriaMetrics query CLI (port of query-vm.py).

All functionality preserved from the original script, restructured
for click and LLM-compact output (no ANSI colors).
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import click

from hops._format import info, kv
from hops._runner import run

VMSINGLE_URL = "http://vmsingle-victoria-metrics-k8s-stack.observability:8428"
VMALERT_URL = "http://vmalert-victoria-metrics-k8s-stack.observability:8080"

IGNORED_ALERTS = {"Watchdog", "InfoInhibitor"}
IGNORED_ALERT_PREFIXES = ("Unifi",)

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
_REDUNDANT_LABEL_PAIRS = {"instance": "nodename"}


def is_ignored_alert(alertname: str) -> bool:
    if alertname in IGNORED_ALERTS:
        return True
    return alertname.startswith(IGNORED_ALERT_PREFIXES)


# --- Time range handling ---


@dataclass
class TimeRange:
    start: str | None = None
    end: str | None = None

    @classmethod
    def from_options(
        cls,
        time_from: str | None,
        time_to: str | None,
        time_at: str | None = None,
        window: str = "10m",
    ) -> TimeRange:
        if time_at:
            half_sec = cls._duration_to_seconds(window) // 2
            at_dt = (
                datetime.now(tz=timezone.utc)
                if time_at == "now"
                else datetime.fromisoformat(time_at)
            )
            if at_dt.tzinfo is None:
                at_dt = at_dt.astimezone()
            at_utc = at_dt.astimezone(timezone.utc)
            start_dt = at_utc - timedelta(seconds=half_sec)
            end_dt = at_utc + timedelta(seconds=half_sec)
            fmt = "%Y-%m-%dT%H:%M:%S"
            return cls(start=start_dt.strftime(fmt), end=end_dt.strftime(fmt))
        return cls(start=time_from, end=time_to)

    def is_current(self) -> bool:
        return self.start is None

    def to_duration(self) -> str:
        if self.start is None:
            raise ValueError("Cannot convert None start to duration")
        if self._is_duration(self.start):
            return self.start
        start_dt = datetime.fromisoformat(self.start.replace("Z", "+00:00"))
        end_dt = self._parse_end_time()
        delta = end_dt - start_dt
        return f"{int(delta.total_seconds())}s"

    def to_promql_range(self) -> str:
        return f"[{self.to_duration()}]"

    def to_range_params(self, step: str = "1m") -> dict[str, str]:
        params: dict[str, str] = {"step": step}
        if self.start:
            params["start"] = (
                f"-{self.start}" if self._is_duration(self.start) else self.start
            )
        if self.end:
            params["end"] = f"-{self.end}" if self._is_duration(self.end) else self.end
        return params

    def _parse_end_time(self) -> datetime:
        if self.end is None:
            return datetime.now(timezone.utc)
        if self._is_duration(self.end):
            seconds = self._duration_to_seconds(self.end)
            return datetime.now(timezone.utc).replace(microsecond=0) - timedelta(
                seconds=seconds
            )
        return datetime.fromisoformat(self.end.replace("Z", "+00:00"))

    @staticmethod
    def _is_duration(value: str) -> bool:
        return bool(re.match(r"^\d+[smhdw]$", value))

    @staticmethod
    def _duration_to_seconds(duration: str) -> int:
        unit = duration[-1]
        value = int(duration[:-1])
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
        return value * multipliers.get(unit, 1)


# --- API helpers ---


def kubectl_curl(url: str) -> dict[str, Any]:
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
    result = run(cmd, timeout=30, check=False)
    if result.returncode != 0:
        msg = (result.stderr or "").strip().split("\n")[0]
        info(f"error: curl failed: {msg}")
        sys.exit(1)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        info("error: invalid JSON from VictoriaMetrics")
        sys.exit(1)


def query_vm(endpoint: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    url = f"{VMSINGLE_URL}{endpoint}"
    if params:
        url = f"{url}?{urlencode(params)}"
    return kubectl_curl(url)


def query_vmalert(endpoint: str) -> dict[str, Any]:
    return kubectl_curl(f"{VMALERT_URL}{endpoint}")


# --- Formatting helpers ---


def compact_labels(metric: dict[str, str]) -> str:
    interesting = {k: v for k, v in metric.items() if k not in _NOISE_LABELS}
    for drop_key, keep_key in _REDUNDANT_LABEL_PAIRS.items():
        if drop_key in interesting and keep_key in interesting:
            del interesting[drop_key]
    if not interesting:
        interesting = {k: v for k, v in metric.items() if k != "__name__"}
    if len(interesting) == 1:
        return next(iter(interesting.values()))
    return ", ".join(f"{k}={v}" for k, v in interesting.items())


def format_value(val: str) -> str:
    try:
        f = float(val)
    except (ValueError, TypeError):
        return val
    if f != f:
        return "NaN"
    if abs(f) == float("inf"):
        return val
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    abs_f = abs(f)
    if abs_f >= 100:
        return f"{f:.1f}"
    if abs_f >= 1:
        return f"{f:.3f}"
    if abs_f >= 0.001:
        return f"{f:.4f}"
    return f"{f:.6f}"


def format_cpu(value: float) -> str:
    if value < 0.001:
        return f"{value * 1000000:.0f}u"
    elif value < 1:
        return f"{value * 1000:.0f}m"
    return f"{value:.2f}"


def format_memory(value: float) -> str:
    for unit in ["B", "Ki", "Mi", "Gi", "Ti"]:
        if value < 1024.0:
            return f"{value:.1f}{unit}"
        value /= 1024.0
    return f"{value:.1f}Pi"


def format_timestamp(ts: float, local: bool = False) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if local:
        dt = dt.astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def format_labels_list(
    labels: dict[str, str], exclude: set[str] | None = None
) -> list[str]:
    exclude = exclude or set()
    return [f"{k}={v}" for k, v in labels.items() if k not in exclude]


# --- Container stats helper ---


def container_stats(
    namespace: str,
    pod: str,
    container: str,
    time_range: TimeRange,
    metric: str,
    rate: str | None = None,
) -> dict[str, float | None]:
    duration = time_range.to_duration()
    selector = f'namespace="{namespace}",pod=~"{pod}",container="{container}"'
    base = f"{metric}{{{selector}}}"
    expr = f"rate({base}[{rate}])" if rate else base

    stats: dict[str, float | None] = {"current": None, "max": None, "avg": None}

    data = query_vm("/api/v1/query", {"query": expr})
    results = data.get("data", {}).get("result", [])
    if results:
        stats["current"] = float(results[0]["value"][1])

    data = query_vm("/api/v1/query", {"query": f"max_over_time({expr}[{duration}:])"})
    results = data.get("data", {}).get("result", [])
    if results:
        stats["max"] = max(float(r["value"][1]) for r in results)

    data = query_vm("/api/v1/query", {"query": f"avg_over_time({expr}[{duration}:])"})
    results = data.get("data", {}).get("result", [])
    if results:
        stats["avg"] = sum(float(r["value"][1]) for r in results) / len(results)

    return stats


# --- Firing period extraction ---


def _extract_firing_periods(values: list[list]) -> list[tuple[float, float]]:
    periods = []
    start_ts = None
    for ts, val in values:
        is_firing = float(val) == 1
        if is_firing and start_ts is None:
            start_ts = float(ts)
        elif not is_firing and start_ts is not None:
            periods.append((start_ts, float(ts)))
            start_ts = None
    if start_ts is not None and values:
        periods.append((start_ts, float(values[-1][0])))
    return periods


# --- Matrix printer ---


def _print_matrix(results: list[dict[str, Any]]) -> None:
    if not results:
        return

    max_points = 50
    all_values = results[0].get("values", [])
    if not all_values:
        return

    timestamps = [float(ts) for ts, _ in all_values[:max_points]]
    if not timestamps:
        return

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

    series_labels = [compact_labels(r.get("metric", {})) for r in results]
    col_width = 8
    for r in results:
        for _, val in r.get("values", [])[:max_points]:
            col_width = max(col_width, len(format_value(val)))
    col_width += 1

    label_width = max((len(lb) for lb in series_labels), default=5)
    label_width = max(label_width, 5)

    print(f"Date: {date_header}")
    header = " " * label_width + " | "
    header += " ".join(h.rjust(col_width) for h in time_headers)
    print(header)
    print("-" * len(header))

    for i, r in enumerate(results):
        values = r.get("values", [])
        val_map = {float(ts): val for ts, val in values[:max_points]}
        row = series_labels[i].ljust(label_width) + " | "
        row += " ".join(
            format_value(val_map.get(ts, "")).rjust(col_width) for ts in timestamps
        )
        print(row)

    total_points = len(results[0].get("values", []))
    if total_points > max_points:
        print(f"... ({total_points} total points, showing first {max_points})")


# --- Click commands ---


# Common time options
def time_options(default_from=None, support_at=False):
    """Decorator factory for common time range options."""

    def decorator(f):
        f = click.option(
            "--from",
            "time_from",
            default=default_from,
            help="Start time (duration like 24h/7d, or ISO timestamp)",
        )(f)
        f = click.option(
            "--to", "time_to", default=None, help="End time (default: now)"
        )(f)
        if support_at:
            f = click.option(
                "--at",
                "time_at",
                default=None,
                help="Investigate around a specific time (ISO timestamp)",
            )(f)
            f = click.option(
                "--window", default="10m", help="Window size for --at (default: 10m)"
            )(f)
        return f

    return decorator


@click.group()
def cli():
    """Query VictoriaMetrics: PromQL, container stats, alerts."""


@cli.command()
@click.argument("namespace")
@click.argument("pod", metavar="POD_REGEX")
@click.argument("container")
@time_options(default_from="7d")
def cpu(
    namespace: str, pod: str, container: str, time_from: str, time_to: str | None, **_
):
    """CPU usage and throttling for a container."""
    time_range = TimeRange.from_options(time_from, time_to)
    duration = time_range.to_duration()

    stats = container_stats(
        namespace,
        pod,
        container,
        time_range,
        "container_cpu_usage_seconds_total",
        rate="5m",
    )

    selector = f'namespace="{namespace}",pod=~"{pod}",container="{container}"'
    throttle_query = (
        f"(sum(increase(container_cpu_cfs_throttled_periods_total{{{selector}}}[{duration}]))"
        f" / sum(increase(container_cpu_cfs_periods_total{{{selector}}}[{duration}]))) * 100"
    )
    throttle_data = query_vm("/api/v1/query", {"query": throttle_query})
    throttle_results = throttle_data.get("data", {}).get("result", [])
    throttle_pct = float(throttle_results[0]["value"][1]) if throttle_results else None

    pairs = []
    if stats["current"] is not None:
        pairs.append(("Current (5m rate)", f"{format_cpu(stats['current'])} cores"))
    else:
        pairs.append(("Current", "No data"))
    if stats["max"] is not None:
        pairs.append((f"Max ({duration})", f"{format_cpu(stats['max'])} cores"))
    if stats["avg"] is not None:
        pairs.append((f"Avg ({duration})", f"{format_cpu(stats['avg'])} cores"))
    if throttle_pct is not None:
        flag = " (!)" if throttle_pct > 25 else ""
        pairs.append((f"Throttled ({duration})", f"{throttle_pct:.2f}%{flag}"))
    kv(pairs)


@cli.command()
@click.argument("namespace")
@click.argument("pod", metavar="POD_REGEX")
@click.argument("container")
@time_options(default_from="7d")
def memory(
    namespace: str, pod: str, container: str, time_from: str, time_to: str | None, **_
):
    """Memory usage for a container."""
    time_range = TimeRange.from_options(time_from, time_to)
    duration = time_range.to_duration()

    stats = container_stats(
        namespace, pod, container, time_range, "container_memory_working_set_bytes"
    )

    pairs = []
    if stats["current"] is not None:
        pairs.append(("Current", format_memory(stats["current"])))
    else:
        pairs.append(("Current", "No data"))
    if stats["max"] is not None:
        pairs.append((f"Max ({duration})", format_memory(stats["max"])))
    if stats["avg"] is not None:
        pairs.append((f"Avg ({duration})", format_memory(stats["avg"])))
    kv(pairs)


@cli.command("query")
@click.argument("promql")
@click.option("--step", default="1m", help="Step interval for range queries")
@click.option("--hide-zero", is_flag=True, help="Hide all-zero series")
@click.option("--json", "json_mode", is_flag=True, help="Output raw JSON")
@time_options(support_at=True)
def raw_query(
    promql: str,
    step: str,
    hide_zero: bool,
    json_mode: bool,
    time_from: str | None,
    time_to: str | None,
    time_at: str | None = None,
    window: str = "10m",
):
    """Execute a raw PromQL query."""
    time_range = TimeRange.from_options(time_from, time_to, time_at, window)

    if time_range.is_current():
        data = query_vm("/api/v1/query", {"query": promql})
    else:
        params = {"query": promql, **time_range.to_range_params(step)}
        data = query_vm("/api/v1/query_range", params)

    if json_mode:
        print(json.dumps(data, indent=2))
        return

    results = data.get("data", {}).get("result", [])
    result_type = data.get("data", {}).get("resultType", "unknown")

    if not results:
        info("No results")
        return

    suffix = ""
    if hide_zero and result_type == "matrix":
        original_count = len(results)
        results = [
            r for r in results if any(float(val) != 0 for _, val in r.get("values", []))
        ]
        hidden = original_count - len(results)
        suffix = f" ({hidden} all-zero hidden)" if hidden else ""
        if not results:
            info(f"No results (all {original_count} series were zero)")
            return

    info(f"{result_type}, {len(results)} series{suffix}")
    print()

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
        info(f"... {len(results) - max_series} more series")


@cli.command()
@click.argument("name", required=False)
@click.option("--json", "json_mode", is_flag=True, help="Output raw JSON")
def labels(name: str | None, json_mode: bool):
    """List label names or values for a specific label."""
    if name:
        data = query_vm(f"/api/v1/label/{name}/values")
        title = f"Values for '{name}'"
    else:
        data = query_vm("/api/v1/labels")
        title = "All labels"

    values = data.get("data", [])

    if json_mode:
        print(json.dumps(values, indent=2))
        return

    info(f"{title} ({len(values)} total)")
    for v in values:
        print(v)


@cli.command("metrics")
@click.option(
    "-f", "--filter", "pattern", default=None, help="Filter pattern (case-insensitive)"
)
@click.option("--json", "json_mode", is_flag=True, help="Output raw JSON")
def list_metrics(pattern: str | None, json_mode: bool):
    """List metric names with optional filter."""
    data = query_vm("/api/v1/label/__name__/values")
    values = data.get("data", [])
    if pattern:
        p = pattern.lower()
        values = [v for v in values if p in v.lower()]

    if json_mode:
        print(json.dumps(values, indent=2))
        return

    title = f"Metrics matching '{pattern}'" if pattern else "All metrics"
    info(f"{title} ({len(values)} total)")
    for v in values:
        print(v)


@cli.command("alerts")
@click.option(
    "-s",
    "--state",
    default="firing",
    type=click.Choice(["firing", "pending", "inactive", "all"]),
    help="Filter by state (current mode only)",
)
@click.option("--json", "json_mode", is_flag=True, help="Output raw JSON")
@time_options()
def alerts_cmd(
    state: str, json_mode: bool, time_from: str | None, time_to: str | None, **_
):
    """List alerts (current or historical with --from)."""
    time_range = TimeRange.from_options(time_from, time_to)

    if time_range.is_current():
        _alerts_current(state, json_mode)
    else:
        _alerts_historical(time_range, json_mode)


def _alerts_current(state: str, json_mode: bool) -> None:
    data = query_vmalert("/api/v1/alerts")
    all_alerts = data.get("data", {}).get("alerts", [])
    states = ["firing", "pending", "inactive"] if state == "all" else [state]
    filtered = [
        a
        for a in all_alerts
        if a.get("state") in states
        and not is_ignored_alert(a.get("labels", {}).get("alertname", ""))
    ]

    if json_mode:
        print(json.dumps(filtered, indent=2))
        return

    if not filtered:
        info(f"No alerts in {state} state")
        return

    for alert in filtered:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        severity = labels.get("severity", "none")
        print(f"[{severity}] {labels.get('alertname')} ({alert.get('state')})")
        print(
            f"  {annotations.get('summary', annotations.get('description', 'No description'))}"
        )
        print(f"  Expression: {alert.get('expression', 'N/A')}")
        relevant = format_labels_list(
            labels, exclude={"alertname", "alertgroup", "prometheus", "severity"}
        )
        if relevant:
            print(f"  Labels: {', '.join(relevant[:5])}")
        print()


def _alerts_historical(time_range: TimeRange, json_mode: bool) -> None:
    duration = time_range.to_duration()
    query_str = f'topk(20, sum(changes(ALERTS{{alertstate="firing"}}[{duration}])) by (alertname,severity))'
    data = query_vm("/api/v1/query", {"query": query_str})
    results = data.get("data", {}).get("result", [])

    if json_mode:
        print(json.dumps(results, indent=2))
        return

    if not results:
        info(f"No alerts fired in last {duration}")
        return

    info(f"Alerts fired in last {duration}:")
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
        print(f"  [{severity}] {alertname} - {count} times")


@cli.command("alert")
@click.argument("name")
@click.option("--json", "json_mode", is_flag=True, help="Output raw JSON")
@time_options()
def alert_detail(
    name: str, json_mode: bool, time_from: str | None, time_to: str | None, **_
):
    """Detailed alert information (current or historical with --from)."""
    time_range = TimeRange.from_options(time_from, time_to)

    if time_range.is_current():
        _alert_current(name, json_mode)
    else:
        _alert_historical(name, time_range, json_mode)


def _alert_current(name: str, json_mode: bool) -> None:
    data = query_vmalert("/api/v1/alerts")
    matches = [
        a
        for a in data.get("data", {}).get("alerts", [])
        if a.get("labels", {}).get("alertname") == name
    ]
    if not matches:
        info(f"error: no active alert found: {name}")
        info("hint: use --from <duration> to search historical alerts")
        sys.exit(1)

    alert = matches[0]
    if json_mode:
        print(json.dumps(alert, indent=2))
        return

    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    pairs = [
        ("Alert", labels.get("alertname", "")),
        ("State", alert.get("state", "")),
        ("Severity", labels.get("severity", "none")),
        ("Value", str(alert.get("value", "N/A"))),
        ("Active Since", alert.get("activeAt", "N/A")),
        ("Expression", alert.get("expression", "N/A")),
    ]
    kv(pairs)
    if labels:
        print("\nLabels:")
        for k, v in labels.items():
            print(f"  {k}: {v}")
    if annotations:
        print("\nAnnotations:")
        for k, v in annotations.items():
            print(f"  {k}: {v}")

    # Auto-diagnose absent() expressions: the typical failure mode is label
    # drift where the metric exists but under a different label value. Show
    # the caller what IS present for the base metric so the mismatch is
    # immediately visible instead of requiring a follow-up count-by query.
    debug = _analyze_absent_expression(alert.get("expression", ""))
    if debug:
        print("\nRoot cause analysis (absent() expression):")
        kv(debug, indent=2)


_ABSENT_RE = re.compile(r"absent(?:_over_time)?\(\s*([a-zA-Z_:][\w:]*)\s*\{([^}]*)\}")
_LABEL_PAIR_RE = re.compile(r'(\w+)\s*(?:=|=~)\s*"([^"]*)"')


def _analyze_absent_expression(expression: str) -> list[tuple[str, str]]:
    """For `absent(metric{k=v,...})` expressions, return diagnostic rows.

    Queries the base metric grouped by each expected label and reports what
    actual values exist. When the alert fires, this surfaces the mismatch
    (e.g., expected job="kube-controller-manager", present job values
    include "victoria-metrics-k8s-stack-kube-controller-manager") in a
    single call instead of requiring a manual count-by follow-up.
    """
    m = _ABSENT_RE.search(expression)
    if not m:
        return []
    metric, labels_str = m.group(1), m.group(2)
    label_pairs = _LABEL_PAIR_RE.findall(labels_str)
    if not label_pairs:
        return []

    rows: list[tuple[str, str]] = []
    for key, expected in label_pairs:
        data = query_vm("/api/v1/query", {"query": f"count by ({key}) ({metric})"})
        results = data.get("data", {}).get("result", [])
        present = sorted(
            {r.get("metric", {}).get(key, "") for r in results if r.get("metric")}
        )
        rows.append((f"Expected {key}", expected))
        if not present:
            rows.append(
                (f"Present {key} values", f"(none; metric {metric!r} has no series)")
            )
        elif expected in present:
            # The expected label IS present but the alert still fires; likely
            # a different selector or a stale vmalert cache. Surface both.
            rows.append(
                (
                    f"Present {key} values",
                    f"includes {expected!r} (check other selectors or vmalert delay)",
                )
            )
        else:
            preview = ", ".join(present[:8])
            if len(present) > 8:
                preview += f", ... ({len(present) - 8} more)"
            rows.append((f"Present {key} values", preview))
    return rows


def _alert_historical(name: str, time_range: TimeRange, json_mode: bool) -> None:
    duration = time_range.to_duration()
    query_str = f'ALERTS{{alertname="{name}",alertstate="firing"}}'
    params = time_range.to_range_params(step="1m")
    params["query"] = query_str
    data = query_vm("/api/v1/query_range", params)
    results = data.get("data", {}).get("result", [])

    if json_mode:
        print(
            json.dumps(
                {"alertname": name, "duration": duration, "instances": results},
                indent=2,
            )
        )
        return

    if not results:
        info(f"No firing instances of {name} in last {duration}")
        return

    info(f"Alert: {name} (historical, last {duration})")
    info(f"Instances: {len(results)}")

    for i, r in enumerate(results):
        labels = r.get("metric", {})
        values = r.get("values", [])
        if not values:
            continue

        firing_periods = _extract_firing_periods(values)
        print(f"\nInstance {i + 1}:")
        severity = labels.get("severity", "none")
        print(f"  Severity: {severity}")
        relevant = format_labels_list(
            labels, exclude={"alertname", "alertstate", "__name__", "severity"}
        )
        if relevant:
            print(f"  Labels: {', '.join(relevant)}")
        if firing_periods:
            print("  Firing periods:")
            for start_ts, end_ts in firing_periods:
                print(f"    {format_timestamp(start_ts)} - {format_timestamp(end_ts)}")


@cli.command()
@click.option("--json", "json_mode", is_flag=True, help="Output raw JSON")
def rules(json_mode: bool):
    """List all alert rules."""
    data = query_vmalert("/api/v1/rules")
    groups = data.get("data", {}).get("groups", [])

    if json_mode:
        print(json.dumps(groups, indent=2))
        return

    for group in groups:
        print(f"Group: {group.get('name')}")
        for rule in group.get("rules", []):
            print(f"  {rule.get('name')} ({rule.get('type')}) - {rule.get('state')}")
        print()
