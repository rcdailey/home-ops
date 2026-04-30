"""VictoriaMetrics alert commands: current, historical, rules."""

from __future__ import annotations

import json
import re
import sys

import click

from hops._format import format_labels_list, format_timestamp, info, kv
from hops._time import TimeRange, time_options
from hops.query._vm import is_ignored_alert, query_vm, query_vmalert


@click.group()
def cli():
    """Alert monitoring and investigation."""


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
    query_str = (
        f'topk(20, sum(changes(ALERTS{{alertstate="firing"}}[{duration}])) '
        f"by (alertname,severity))"
    )
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
    """For absent(metric{k=v,...}) expressions, return diagnostic rows.

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


@cli.command("rules")
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
