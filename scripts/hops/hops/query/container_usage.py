"""Container CPU and memory history from OpenTelemetry kubeletstats metrics.

The node Collector's kubeletstats receiver owns container usage. Its series
carry OTel resource labels (k8s_namespace_name, k8s_pod_name,
k8s_container_name), not the cAdvisor names (namespace, pod, container) that
Prometheus-oriented PromQL assumes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from hops.core.time import TimeRange
from hops.query._vm import query_vm

BUCKETS = 24

CPU_USAGE = "container_cpu_usage"
MEMORY_WORKING_SET = "container_memory_working_set_bytes"
CPU_REQUEST = "k8s_container_cpu_request"
CPU_LIMIT = "k8s_container_cpu_limit"
MEMORY_REQUEST = "k8s_container_memory_request_bytes"
MEMORY_LIMIT = "k8s_container_memory_limit_bytes"


@dataclass
class Bucket:
    start: float
    peak: float
    avg: float


@dataclass
class Usage:
    current: float | None
    peak: float | None
    peak_at: float | None
    avg: float | None
    buckets: list[Bucket]
    request: float | None
    limit: float | None


def workload_pod_regex(pods: list[dict]) -> str:
    """Regex matching every pod the workloads behind these pods ever created.

    Matching only the current pod names would hide history from before the
    latest rollout or restart, which is usually the period being investigated.
    PromQL regexes are fully anchored, so the generated suffixes cannot match
    sibling workloads that share a name prefix (silo vs silo-valkey).
    """
    patterns = set()
    for pod in pods:
        meta = pod.get("metadata", {})
        name = meta.get("name", "")
        generate = meta.get("generateName", "")
        template_hash = meta.get("labels", {}).get("pod-template-hash", "")
        if generate and template_hash and generate.endswith(f"{template_hash}-"):
            base = generate.removesuffix(f"{template_hash}-")
            patterns.add(_escape(base) + "[a-z0-9]+-[a-z0-9]+")
        elif generate:
            patterns.add(_escape(generate) + "[a-z0-9]+")
        elif name:
            patterns.add(_escape(name))
    return "(?:" + "|".join(sorted(patterns)) + ")"


def _escape(value: str) -> str:
    return re.escape(value).replace(r"\-", "-").replace("\\", "\\\\")


def selector(namespace: str, pod_regex: str, container: str) -> str:
    return (
        f'k8s_namespace_name="{namespace}",k8s_pod_name=~"{pod_regex}",'
        f'k8s_container_name="{container}"'
    )


def usage(
    metric: str,
    request_metric: str,
    limit_metric: str,
    match: str,
    time_range: TimeRange,
) -> Usage:
    """Usage of the busiest matching pod: now, over the range, and per bucket."""
    series = f"{metric}{{{match}}}"
    step = time_range.auto_step()
    params = time_range.to_range_params(step)
    peaks = _points(f"max(max_over_time({series}[{step}]))", params)
    avgs = _points(f"max(avg_over_time({series}[{step}]))", params)

    peak = peak_at = None
    if peaks:
        peak_at, peak = max(peaks, key=lambda point: point[1])
    avg = sum(value for _, value in avgs) / len(avgs) if avgs else None

    return Usage(
        current=_instant(f"max(last_over_time({series}[5m]))"),
        peak=peak,
        peak_at=peak_at,
        avg=avg,
        buckets=_bucket(peaks, avgs),
        request=_instant(f"max(last_over_time({request_metric}{{{match}}}[5m]))"),
        limit=_instant(f"max(last_over_time({limit_metric}{{{match}}}[5m]))"),
    )


def _points(query: str, params: dict[str, str]) -> list[tuple[float, float]]:
    data = query_vm("/api/v1/query_range", {"query": query, **params})
    results = data.get("data", {}).get("result", [])
    if not results:
        return []
    return [(float(ts), float(value)) for ts, value in results[0].get("values", [])]


def _instant(query: str) -> float | None:
    data = query_vm("/api/v1/query", {"query": query})
    results = data.get("data", {}).get("result", [])
    return float(results[0]["value"][1]) if results else None


def _bucket(
    peaks: list[tuple[float, float]], avgs: list[tuple[float, float]]
) -> list[Bucket]:
    """Fold fine-grained points into at most BUCKETS equal time slices."""
    if not peaks:
        return []
    first, last = peaks[0][0], peaks[-1][0]
    width = max((last - first) / BUCKETS, 1.0)

    def index(ts: float) -> int:
        return min(int((ts - first) / width), BUCKETS - 1)

    peak_by: dict[int, float] = {}
    for ts, value in peaks:
        i = index(ts)
        peak_by[i] = max(peak_by.get(i, value), value)
    avg_by: dict[int, list[float]] = {}
    for ts, value in avgs:
        avg_by.setdefault(index(ts), []).append(value)

    buckets = []
    for i in sorted(peak_by):
        values = avg_by.get(i) or [peak_by[i]]
        buckets.append(
            Bucket(
                start=first + i * width, peak=peak_by[i], avg=sum(values) / len(values)
            )
        )
    return buckets


def bucket_labels(buckets: list[Bucket]) -> list[str]:
    """Local bucket start times, dated whenever the buckets cross midnight."""
    moments = [datetime.fromtimestamp(b.start).astimezone() for b in buckets]
    dated = len({m.date() for m in moments}) > 1
    return [m.strftime("%m-%d %H:%M" if dated else "%H:%M") for m in moments]
