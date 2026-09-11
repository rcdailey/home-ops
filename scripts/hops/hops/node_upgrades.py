"""Tuppr upgrade progress correlated with node and Job state."""

from __future__ import annotations

import json

import click

from hops.core.format import age_str, section, table
from hops.core.nodes import get_all
from hops.core.runner import kubectl_json, run


def _optional_json(args: list[str]) -> dict | None:
    result = run(args, timeout=15)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _job_phase(status: dict) -> str:
    if status.get("succeeded"):
        return "Succeeded"
    if status.get("failed"):
        return "Failed"
    if status.get("active"):
        return "Running"
    return "Pending"


def _show_active_job(resource: dict) -> None:
    metadata = resource.get("metadata", {})
    upgrade_status = resource.get("status", {})
    namespace = metadata.get("namespace", "default")
    job_name = upgrade_status.get("jobName")
    if not job_name:
        return

    job = _optional_json(
        ["kubectl", "get", "job", job_name, "-n", namespace, "-o", "json"]
    )
    if job is None:
        return

    pods = _optional_json(
        [
            "kubectl",
            "get",
            "pods",
            "-n",
            namespace,
            "-l",
            f"job-name={job_name}",
            "-o",
            "json",
        ]
    )
    pod_items = (pods or {}).get("items", [])
    pod = pod_items[0] if pod_items else {}
    pod_status = pod.get("status", {})
    restarts = sum(
        item.get("restartCount", 0) for item in pod_status.get("containerStatuses", [])
    )
    labels = job.get("metadata", {}).get("labels", {})
    job_status = job.get("status", {})

    section("ACTIVE JOB")
    table(
        ["JOB", "STATE", "TARGET", "RUNS ON", "POD", "RESTARTS", "AGE"],
        [
            [
                job_name,
                _job_phase(job_status),
                labels.get("tuppr.home-operations.com/target-node", "?"),
                pod.get("spec", {}).get("nodeName", "?"),
                pod_status.get("phase", "?"),
                str(restarts),
                age_str(job_status.get("startTime")),
            ]
        ],
    )

    logs = run(
        ["kubectl", "logs", "-n", namespace, f"job/{job_name}", "--tail", "20"],
        timeout=20,
    )
    if logs.returncode == 0 and logs.stdout.strip():
        section("JOB LOG")
        click.echo(logs.stdout.strip())

    events = _optional_json(
        [
            "kubectl",
            "get",
            "events",
            "-n",
            namespace,
            "--field-selector",
            f"involvedObject.name={job_name},type=Warning",
            "-o",
            "json",
        ]
    )
    warnings = [item.get("message", "?") for item in (events or {}).get("items", [])]
    if warnings:
        section("WARNINGS")
        click.echo("\n".join(warnings))


def show_upgrades() -> None:
    """Show Tuppr resources, Kubernetes node versions, and active Job evidence."""
    data = kubectl_json("kubernetesupgrades,talosupgrades")
    resources = data.get("items", [])

    section("UPGRADES")
    rows = []
    for resource in resources:
        metadata = resource.get("metadata", {})
        spec = resource.get("spec", {})
        status = resource.get("status", {})
        target = spec.get("kubernetes", spec.get("talos", {})).get("version", "?")
        completed = len(status.get("completedNodes", []))
        failed = len(status.get("failedNodes", []))
        rows.append(
            [
                resource.get("kind", "?").removesuffix("Upgrade"),
                metadata.get("name", "?"),
                status.get("phase", "Unknown"),
                status.get("currentVersion", "?"),
                target,
                status.get("controllerNode") or status.get("currentNode") or "-",
                str(completed) if completed else "-",
                str(failed) if failed else "-",
                str(status.get("retries", "-")),
                age_str(status.get("lastUpdated")),
            ]
        )
    table(
        [
            "TYPE",
            "NAME",
            "PHASE",
            "FROM",
            "TO",
            "NODE",
            "DONE",
            "FAILED",
            "RETRIES",
            "UPDATED",
        ],
        rows,
    )

    section("NODES")
    nodes = get_all()
    table(
        ["NODE", "STATUS", "KUBELET"],
        [[node.name, node.status, node.kubelet] for node in nodes],
    )

    active = next(
        (
            resource
            for resource in resources
            if resource.get("status", {}).get("jobName")
            and resource.get("status", {}).get("phase") not in {"Completed", "Failed"}
        ),
        None,
    )
    if active is not None:
        _show_active_job(active)
