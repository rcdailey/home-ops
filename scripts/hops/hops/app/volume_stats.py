"""Mounted PVC usage from the kubelet summary API."""

from __future__ import annotations

import json

from hops.core.format import human_bytes, info, section, table, truncate
from hops.core.runner import run


def _node_summaries(pods: list[dict]) -> tuple[dict, dict]:
    summaries = {}
    errors = {}
    nodes = {pod.get("spec", {}).get("nodeName") for pod in pods}
    for node in sorted(node for node in nodes if node):
        result = run(
            [
                "kubectl",
                "get",
                "--raw",
                f"/api/v1/nodes/{node}/proxy/stats/summary",
            ],
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            errors[node] = truncate((result.stderr or "query failed").splitlines()[0])
            continue
        try:
            summaries[node] = json.loads(result.stdout)
        except json.JSONDecodeError:
            errors[node] = "invalid kubelet response"
    return summaries, errors


def _mounted_pvcs(pod: dict) -> list[str]:
    spec = pod.get("spec", {})
    containers = [*spec.get("containers", []), *spec.get("initContainers", [])]
    mounted = {
        mount.get("name")
        for container in containers
        for mount in container.get("volumeMounts", [])
    }
    return [
        volume["persistentVolumeClaim"].get("claimName", "?")
        for volume in spec.get("volumes", [])
        if volume.get("name") in mounted and volume.get("persistentVolumeClaim")
    ]


def _pod_stats(summary: dict, pod: dict) -> dict[str, dict]:
    meta = pod.get("metadata", {})
    item = next(
        (
            item
            for item in summary.get("pods", [])
            if item.get("podRef", {}).get("name") == meta.get("name")
            and item.get("podRef", {}).get("namespace") == meta.get("namespace")
        ),
        {},
    )
    return {
        volume.get("pvcRef", {}).get("name"): volume
        for volume in item.get("volume", [])
        if volume.get("pvcRef")
    }


def diagnose_volumes(pods: list[dict]) -> None:
    """Show filesystem capacity for PVCs mounted by the selected pods."""
    pod_volumes = [(pod, _mounted_pvcs(pod)) for pod in pods]
    pod_volumes = [(pod, pvcs) for pod, pvcs in pod_volumes if pvcs]
    if not pod_volumes:
        return

    summaries, errors = _node_summaries([pod for pod, _ in pod_volumes])

    rows = []
    for pod, pvcs in pod_volumes:
        meta = pod.get("metadata", {})
        pod_name = meta.get("name", "?")
        node = pod.get("spec", {}).get("nodeName")
        stats_by_pvc = _pod_stats(summaries.get(node, {}), pod)
        for pvc in pvcs:
            stats = stats_by_pvc.get(pvc, {})
            capacity = stats.get("capacityBytes")
            used = stats.get("usedBytes")
            available = stats.get("availableBytes")
            use_pct = f"{used / capacity * 100:.1f}%" if capacity else "-"
            rows.append(
                [
                    pod_name,
                    pvc,
                    human_bytes(capacity) if capacity is not None else "-",
                    human_bytes(used) if used is not None else "-",
                    human_bytes(available) if available is not None else "-",
                    use_pct,
                ]
            )

    section("PVC STORAGE")
    table(["POD", "PVC", "CAPACITY", "USED", "AVAILABLE", "USE%"], rows)
    for node, error in errors.items():
        info(f"{node}: storage stats unavailable ({error})")
