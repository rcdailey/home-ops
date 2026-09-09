"""Horizontal Pod Autoscaler diagnostics."""

from __future__ import annotations

from urllib.parse import quote

import click

from hops.app import cli
from hops.core.format import info, kv, section, table, truncate
from hops.core.runner import kubectl_json, run_json


def _find_hpa(name: str, namespace: str | None) -> dict:
    data = kubectl_json("horizontalpodautoscalers", namespace=namespace)
    matches = [
        item for item in data.get("items", []) if item["metadata"]["name"] == name
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        info(f"error: could not find HPA {name!r}")
    else:
        namespaces = ", ".join(item["metadata"]["namespace"] for item in matches)
        info(f"error: HPA {name!r} exists in multiple namespaces: {namespaces}")
    raise SystemExit(1)


def _selector(metric: dict) -> str:
    match_labels = metric.get("selector", {}).get("matchLabels", {})
    return ",".join(f"{key}={value}" for key, value in sorted(match_labels.items()))


def _external_values(namespace: str, metric: dict) -> list[str]:
    name = metric["name"]
    selector = _selector(metric)
    path = f"/apis/external.metrics.k8s.io/v1beta1/namespaces/{namespace}/{name}"
    if selector:
        path += f"?labelSelector={quote(selector)}"
    data = run_json(["kubectl", "get", "--raw", path])
    return [item.get("value", "?") for item in data.get("items", [])]


@cli.command()
@click.argument("app")
@click.option("-n", "--namespace", help="Namespace (auto-detected if omitted)")
def autoscale(app: str, namespace: str | None):
    """Correlate an HPA's state, external metric, conditions, and events."""
    hpa = _find_hpa(app, namespace)
    metadata = hpa["metadata"]
    hpa_namespace = str(metadata["namespace"])
    spec = hpa.get("spec", {})
    status = hpa.get("status", {})
    target = spec.get("scaleTargetRef", {})

    kv(
        [
            ("HPA", f"{hpa_namespace}/{metadata['name']}"),
            ("Target", f"{target.get('kind', '?')}/{target.get('name', '?')}"),
            (
                "Replicas",
                "current={} desired={}".format(
                    status.get("currentReplicas", "?"),
                    status.get("desiredReplicas", "?"),
                ),
            ),
            (
                "Bounds",
                f"min={spec.get('minReplicas', 1)} max={spec.get('maxReplicas', '?')}",
            ),
        ]
    )

    rows = []
    for metric_spec in spec.get("metrics", []):
        external = metric_spec.get("external")
        if not external:
            continue
        metric = external.get("metric", {})
        target_spec = external.get("target", {})
        target_value = target_spec.get("value", target_spec.get("averageValue", "?"))
        values = _external_values(hpa_namespace, metric)
        rows.append(
            [
                metric.get("name", "?"),
                _selector(metric) or "-",
                str(target_value),
                ",".join(values) or "missing",
            ]
        )
    if rows:
        section("EXTERNAL METRICS")
        table(["METRIC", "SELECTOR", "TARGET", "LIVE"], rows)

    conditions = status.get("conditions", [])
    if conditions:
        section("CONDITIONS")
        table(
            ["TYPE", "STATUS", "REASON", "MESSAGE"],
            [
                [
                    condition.get("type", "?"),
                    condition.get("status", "?"),
                    condition.get("reason", "?"),
                    truncate(condition.get("message", ""), 100),
                ]
                for condition in conditions
            ],
        )

    events = kubectl_json(
        "events",
        f"--field-selector=involvedObject.kind=HorizontalPodAutoscaler,"
        f"involvedObject.name={metadata['name']}",
        namespace=hpa_namespace,
    ).get("items", [])
    if events:
        section("EVENTS")
        table(
            ["TYPE", "REASON", "MESSAGE"],
            [
                [
                    event.get("type", "?"),
                    event.get("reason", "?"),
                    truncate(event.get("message", ""), 100),
                ]
                for event in events[-10:]
            ],
        )
