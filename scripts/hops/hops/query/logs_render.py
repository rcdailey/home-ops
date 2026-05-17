"""Display helpers for VictoriaLogs query output.

Pure formatting functions with no click dependency.
"""

from __future__ import annotations

import json
from datetime import datetime

from hops.core.format import info, table


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


def _format_metric_label(metric: dict[str, str]) -> str:
    """Compact label string from a stats metric dict."""
    filtered = {k: v for k, v in metric.items() if k != "__name__"}
    if not filtered:
        return "(all)"
    if len(filtered) == 1:
        return next(iter(filtered.values())) or "(empty)"
    return ", ".join(f"{k}={v}" for k, v in filtered.items())


def _format_ts(ts: str | float) -> str:
    """Format a timestamp (ISO string or epoch) to HH:MM."""
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.strftime("%H:%M")
        except (ValueError, TypeError):
            return str(ts)
    try:
        dt = datetime.fromtimestamp(float(ts), tz=datetime.now().astimezone().tzinfo)
        return dt.strftime("%H:%M")
    except (ValueError, TypeError, OSError):
        return str(ts)


def _print_vector(results: list[dict]) -> None:
    """Format Prometheus-style vector results as a table."""
    if not results:
        info("No results")
        return
    rows = []
    for r in results:
        label = _format_metric_label(r.get("metric", {}))
        val = r.get("value", [None, "N/A"])
        try:
            v = float(val[1])
            value_str = str(int(v)) if v == int(v) else f"{v:.2f}"
        except (ValueError, TypeError, IndexError):
            value_str = str(val[1]) if len(val) > 1 else "N/A"
        rows.append([label, value_str])
    stat_name = results[0].get("metric", {}).get("__name__", "VALUE")
    table(["METRIC", stat_name], rows)


def _print_matrix_table(results: list[dict]) -> None:
    """Format Prometheus-style matrix results as a time-series table."""
    if not results:
        info("No results")
        return

    # Collect all timestamps across all series
    all_ts: list[float] = []
    for r in results:
        for ts, _ in r.get("values", []):
            all_ts.append(float(ts))
    all_ts = sorted(set(all_ts))

    if not all_ts:
        info("No data points")
        return

    # Limit columns for readability
    max_cols = 12
    if len(all_ts) > max_cols:
        step = len(all_ts) // max_cols
        sampled = all_ts[::step][:max_cols]
        info(f"({len(all_ts)} points, showing {len(sampled)} samples)")
    else:
        sampled = all_ts

    time_headers = [_format_ts(ts) for ts in sampled]
    headers = ["METRIC"] + time_headers

    rows = []
    for r in results:
        label = _format_metric_label(r.get("metric", {}))
        val_map = {float(ts): val for ts, val in r.get("values", [])}
        cells = []
        for ts in sampled:
            raw = val_map.get(ts)
            if raw is None:
                cells.append("-")
            else:
                try:
                    v = float(raw)
                    cells.append(str(int(v)) if v == int(v) else f"{v:.2f}")
                except (ValueError, TypeError):
                    cells.append(str(raw))
        rows.append([label] + cells)

    table(headers, rows)


def _print_hits_table(data: dict) -> None:
    """Format VictoriaLogs hits response as a time-series table."""
    hit_list = data.get("hits", [])
    if not hit_list:
        info("No hits")
        return

    for hit in hit_list:
        fields = hit.get("fields", {})
        timestamps = hit.get("timestamps", [])
        values = hit.get("values", [])
        total = hit.get("total", sum(values))

        if fields:
            label = ", ".join(f"{k}={v}" for k, v in fields.items())
        else:
            label = "(all)"

        info(f"{label}  total={total}")
        if timestamps:
            rows = []
            for ts, val in zip(timestamps, values):
                rows.append([_format_ts(ts), str(val)])
            table(["TIME", "COUNT"], rows)
