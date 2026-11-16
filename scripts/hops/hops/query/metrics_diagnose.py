"""Explain why a PromQL query matched nothing.

Most empty results come from Prometheus-convention names that do not exist
here: OTel pipelines rename metrics (container_cpu_usage, not
container_cpu_usage_seconds_total) and labels (k8s_pod_name, not pod). Each
check below names the first missing piece and the closest existing names, so
the caller fixes the query without a separate discovery round.
"""

from __future__ import annotations

import difflib
import re
from urllib.parse import urlencode

from hops.core.format import info
from hops.query._vm import query_vm

_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')
_SELECTOR_RE = re.compile(r"([a-zA-Z_:][\w:]*)?\s*\{([^}]*)\}")
_MATCHER_RE = re.compile(r'(\w+)\s*(=~|!~|!=|=)\s*"((?:[^"\\]|\\.)*)"')
_GROUPING_RE = re.compile(
    r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)"
)
_IDENT_RE = re.compile(r"(?<![\w:.])([a-zA-Z_:][\w:]*)(?![\w:]|\s*\()")
_KEYWORDS = frozenset(
    {"and", "or", "unless", "bool", "offset", "by", "without", "on", "ignoring"}
    | {"group_left", "group_right", "inf", "nan", "atan2", "start", "end"}
)
_MAX_SUGGESTIONS = 5


def diagnose_empty(promql: str) -> None:
    selectors = _selectors(promql)
    metrics = sorted(_metric_names(promql) | {name for name, _ in selectors if name})
    if not metrics:
        return

    known = set(query_vm("/api/v1/label/__name__/values").get("data", []))
    hints: list[str] = []
    for metric in metrics:
        if metric not in known:
            hints.append(_missing_metric_hint(metric, known))
    for metric, matchers in selectors:
        if metric and metric in known:
            hints.extend(_matcher_hints(metric, matchers))

    if not hints:
        hints.append(
            "every metric, label, and exact label value exists; regex matchers, "
            "arithmetic, or the time window exclude all series"
        )
    for hint in hints:
        info(f"  hint: {hint}")


def _selectors(promql: str) -> list[tuple[str, list[tuple[str, str, str]]]]:
    return [
        (name or "", _MATCHER_RE.findall(body))
        for name, body in _SELECTOR_RE.findall(promql)
    ]


def _metric_names(promql: str) -> set[str]:
    """Bare identifiers that are neither functions, keywords, nor durations."""
    stripped = _STRING_RE.sub('""', promql)
    stripped = _GROUPING_RE.sub(" ", stripped)
    stripped = re.sub(r"\{[^}]*\}", " ", stripped)
    stripped = re.sub(r"\[[^\]]*\]", " ", stripped)
    return {
        name for name in _IDENT_RE.findall(stripped) if name.lower() not in _KEYWORDS
    }


def _missing_metric_hint(metric: str, known: set[str]) -> str:
    similar = _similar(metric, known)
    suffix = f"; similar: {', '.join(similar)}" if similar else ""
    return f"metric {metric!r} does not exist{suffix}"


def _matcher_hints(metric: str, matchers: list[tuple[str, str, str]]) -> list[str]:
    labels = set(_labels_for(metric))
    hints = []
    for label, op, value in matchers:
        if label not in labels:
            similar = _similar(label, labels)
            suffix = f"; it has: {', '.join(similar)}" if similar else ""
            hints.append(f"{metric} has no label {label!r}{suffix}")
            continue
        if op != "=":
            continue
        values = set(_label_values(metric, label))
        if value not in values:
            similar = _similar(value, values)
            suffix = f"; similar values: {', '.join(similar)}" if similar else ""
            hints.append(f"{metric} has no {label}={value!r}{suffix}")
    return hints


def _labels_for(metric: str) -> list[str]:
    query = urlencode({"match[]": metric})
    return query_vm(f"/api/v1/labels?{query}").get("data", [])


def _label_values(metric: str, label: str) -> list[str]:
    query = urlencode({"match[]": metric})
    return query_vm(f"/api/v1/label/{label}/values?{query}").get("data", [])


def _similar(name: str, candidates: set[str]) -> list[str]:
    """Closest candidates: containment first (pod -> k8s_pod_name), then spelling."""
    lowered = name.lower()
    contained = sorted(
        (
            c
            for c in candidates
            if lowered in c.lower() or (len(c) >= 4 and c.lower() in lowered)
        ),
        key=lambda c: (abs(len(c) - len(name)), c),
    )
    close = difflib.get_close_matches(name, candidates, n=_MAX_SUGGESTIONS, cutoff=0.6)
    merged = list(dict.fromkeys([*contained, *close]))
    return merged[:_MAX_SUGGESTIONS]
