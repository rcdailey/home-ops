"""VictoriaTraces diagnostic query."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import click

from hops.core.format import info, kv, table, truncate
from hops.core.runner import tools_curl
from hops.core.time import TimeRange, time_options

VT_URL = "http://vt.observability:10428/select/tempo"


def _query_vt(endpoint: str, params: dict[str, str]) -> dict[str, Any]:
    url = f"{VT_URL}{endpoint}?{urlencode(params)}"
    raw = tools_curl(url, service_name="VictoriaTraces")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        info("error: invalid JSON from VictoriaTraces")
        raise SystemExit(1) from None


def _service_names(result: dict[str, Any]) -> list[str]:
    return sorted(
        str(item["value"]) for item in result.get("tagValues", []) if item.get("value")
    )


def _format_start(value: str) -> str:
    try:
        timestamp = int(value) / 1_000_000_000
        return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%H:%M:%S")
    except (OSError, TypeError, ValueError):
        return "?"


def _attribute_value(attributes: list[dict[str, Any]], key: str) -> str:
    for attribute in attributes:
        if attribute.get("key") != key:
            continue
        value = attribute.get("value", {})
        return str(value.get("stringValue", ""))
    return ""


def _summarize_trace(trace_id: str, result: dict[str, Any]) -> dict[str, Any]:
    spans: list[dict[str, str]] = []
    for batch in result.get("batches", []):
        service = _attribute_value(
            batch.get("resource", {}).get("attributes", []), "service.name"
        )
        for scope_spans in batch.get("scopeSpans", []):
            for span in scope_spans.get("spans", []):
                spans.append(
                    {
                        "service": service or "?",
                        "name": str(span.get("name", "?")),
                        "span_id": str(span.get("spanId", "")),
                        "parent_span_id": str(span.get("parentSpanId", "")),
                    }
                )

    span_ids = {span["span_id"] for span in spans}
    roots = [span for span in spans if not span["parent_span_id"]]
    missing_parents = [
        span
        for span in spans
        if span["parent_span_id"] and span["parent_span_id"] not in span_ids
    ]
    services = Counter(span["service"] for span in spans)
    return {
        "trace_id": trace_id,
        "span_count": len(spans),
        "root_spans": roots,
        "missing_parents": missing_parents,
        "services": dict(sorted(services.items())),
    }


def _show_trace(summary: dict[str, Any]) -> None:
    root_spans = summary["root_spans"]
    missing_parents = summary["missing_parents"]
    services = summary["services"]
    kv(
        [
            ("Trace", summary["trace_id"]),
            ("Spans", str(summary["span_count"])),
            ("Root", "present" if root_spans else "missing"),
            ("Missing parents", str(len(missing_parents))),
            (
                "Services",
                ", ".join(f"{name} ({count})" for name, count in services.items()),
            ),
        ]
    )
    if missing_parents:
        click.echo()
        table(
            ("SERVICE", "SPAN", "MISSING PARENT"),
            [
                (span["service"], truncate(span["name"], 50), span["parent_span_id"])
                for span in missing_parents
            ],
        )


@click.command()
@click.option("--service", help="Filter by service.name")
@click.option(
    "--trace-id", help="Inspect a persisted trace and its missing parent boundaries"
)
@click.option("--limit", type=click.IntRange(1, 100), default=20, show_default=True)
@click.option("--json", "json_mode", is_flag=True, help="Output raw correlated data")
@time_options(default_from="1h")
def cli(
    service: str | None,
    trace_id: str | None,
    limit: int,
    json_mode: bool,
    time_from: str,
    time_to: str | None,
    **_: Any,
) -> None:
    """Show recent trace services and representative traces."""
    if trace_id:
        trace = _query_vt(f"/api/traces/{trace_id}", {})
        summary = _summarize_trace(trace_id, trace)
        if summary["span_count"] == 0:
            info(f"error: trace {trace_id} not found")
            raise SystemExit(1)
        if json_mode:
            click.echo(json.dumps(summary, indent=2))
            return
        _show_trace(summary)
        return

    time_range = TimeRange.from_options(time_from, time_to)
    params = time_range.to_epoch_range_params()
    service_params = {**params, "limit": "100"}

    services = _query_vt(
        "/api/v2/search/tag/service.name/values",
        service_params,
    )
    search_params = {**params, "limit": str(limit)}
    if service:
        search_params["q"] = f"{{ resource.service.name = {json.dumps(service)} }}"
    else:
        search_params["q"] = "{ true }"
    traces = _query_vt("/api/search", search_params)

    if json_mode:
        click.echo(json.dumps({"services": services, "search": traces}, indent=2))
        return

    names = _service_names(services)
    rows = []
    for trace in traces.get("traces", []):
        rows.append(
            (
                _format_start(trace.get("startTimeUnixNano", "")),
                str(trace.get("rootServiceName", "?")),
                truncate(str(trace.get("rootTraceName", "?")), 50),
                f"{float(trace.get('durationMs', 0)):.1f}ms",
                str(trace.get("traceID", ""))[:16],
            )
        )

    kv(
        [
            ("Window", time_range.describe()),
            ("Services", str(len(names))),
            ("Traces shown", str(len(rows))),
        ]
    )
    if names:
        click.echo(f"Service names: {', '.join(names)}")
    if rows:
        click.echo()
        table(("START", "SERVICE", "ROOT SPAN", "DURATION", "TRACE"), rows)
    else:
        info("No traces found in this window.")
