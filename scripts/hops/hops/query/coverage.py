"""Correlate running pods with Kubernetes inventory metrics and logs."""

from __future__ import annotations

import json
from typing import Any

import click

from hops.core.format import kv, table
from hops.core.runner import kubectl_json
from hops.query._client import VictoriaLogsClient
from hops.query._vm import query_vm

_LOG_LABEL = "observability.home-ops/logs"
_SIDECAR_ANNOTATION = "sidecar.opentelemetry.io/inject"


def _running_pods(namespace: str | None) -> list[dict[str, Any]]:
    data = kubectl_json("pods", namespace=namespace)
    return [
        pod
        for pod in data.get("items", [])
        if pod.get("status", {}).get("phase") == "Running"
    ]


def _metric_pods() -> set[tuple[str, str]]:
    data = query_vm(
        "/api/v1/query",
        {"query": "max by (k8s_namespace_name, k8s_pod_name) (otel_k8s_pod_phase)"},
    )
    return {
        (
            result.get("metric", {}).get("k8s_namespace_name", ""),
            result.get("metric", {}).get("k8s_pod_name", ""),
        )
        for result in data.get("data", {}).get("result", [])
    }


def _log_pods(time_from: str) -> set[tuple[str, str]]:
    query = '* | stats by ("k8s.namespace.name", "k8s.pod.name") count() as hits'
    data = VictoriaLogsClient().query_stats(query, start=time_from)
    return {
        (
            result.get("metric", {}).get("k8s.namespace.name", ""),
            result.get("metric", {}).get("k8s.pod.name", ""),
        )
        for result in data.get("data", {}).get("result", [])
        if result.get("metric", {}).get("k8s.pod.name")
    }


def _expects_logs(pod: dict[str, Any]) -> bool:
    metadata = pod.get("metadata", {})
    labels = metadata.get("labels", {})
    if labels.get(_LOG_LABEL) == "true":
        return True
    annotation = metadata.get("annotations", {}).get(_SIDECAR_ANNOTATION)
    return annotation not in (None, "false")


@click.command()
@click.option("-n", "--namespace", help="Restrict the pod inventory")
@click.option("--from", "time_from", default="24h", show_default=True)
@click.option("--all", "show_all", is_flag=True, help="Show healthy and opted-out pods")
@click.option("--json", "json_mode", is_flag=True, help="Output correlated pod records")
def cli(
    namespace: str | None,
    time_from: str,
    show_all: bool,
    json_mode: bool,
) -> None:
    """Check telemetry storage coverage for every running pod."""
    pods = _running_pods(namespace)
    metric_pods = _metric_pods()
    log_pods = _log_pods(time_from)
    records = []

    for pod in pods:
        metadata = pod.get("metadata", {})
        key = (metadata.get("namespace", ""), metadata.get("name", ""))
        expects_logs = _expects_logs(pod)
        has_logs = key in log_pods
        log_state = (
            "ok" if expects_logs and has_logs else "missing" if expects_logs else "off"
        )
        records.append(
            {
                "namespace": key[0],
                "pod": key[1],
                "metrics": "ok" if key in metric_pods else "missing",
                "logs": log_state,
            }
        )

    problems = [
        record
        for record in records
        if record["metrics"] == "missing" or record["logs"] == "missing"
    ]
    if json_mode:
        click.echo(json.dumps(records, indent=2))
        return

    configured_logs = sum(record["logs"] != "off" for record in records)
    active_logs = sum(record["logs"] == "ok" for record in records)
    kv(
        [
            ("Running pods", str(len(records))),
            ("Pod metrics present", str(sum(r["metrics"] == "ok" for r in records))),
            ("Logs configured", str(configured_logs)),
            (f"Logs active ({time_from})", str(active_logs)),
            ("Coverage problems", str(len(problems))),
        ]
    )
    selected = records if show_all else problems
    if selected:
        click.echo()
        table(
            ("NAMESPACE", "POD", "POD METRIC", "LOGS"),
            [
                (
                    record["namespace"],
                    record["pod"],
                    record["metrics"],
                    record["logs"],
                )
                for record in selected
            ],
        )
