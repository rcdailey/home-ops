"""Node domain: cluster node information and diagnostics."""

from __future__ import annotations

import json
import re

import click

from hops._click import HelpfulGroup
from hops.core.format import human_bytes, kv, section, table
from hops.core.nodes import get_all, resolve_ip
from hops.core.runner import kubectl_json, run, run_json, run_jsonl

_ISSUE_TERMS = (
    "error",
    "fail",
    "not ready",
    "runtime is down",
    "waiting for service",
)


@click.group(cls=HelpfulGroup)
def cli():
    """Cluster node information and diagnostics."""


def _talos_versions(ips: list[str]) -> dict[str, str]:
    result = run(
        ["talosctl", "version", "--short", "-n", ",".join(ips)],
        timeout=15,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "talosctl failed").strip()
        click.echo(f"error: {message.splitlines()[0]}", err=True)
        raise SystemExit(1)

    versions = {}
    node = None
    for line in result.stdout.splitlines():
        key, separator, value = line.strip().partition(":")
        if not separator:
            continue
        if key == "NODE":
            node = value.strip()
            continue
        if key == "Tag" and node is not None:
            versions[node] = value.strip()
            node = None
    return versions


@cli.command("list")
def list_nodes():
    """Correlate Kubernetes node state with the running Talos version."""
    nodes = get_all()
    talos_versions = _talos_versions([node.ip for node in nodes])
    table(
        ["NODE", "IP", "ROLE", "STATUS", "KUBELET", "TALOS"],
        [
            [
                node.name,
                node.ip,
                node.role,
                node.status,
                node.kubelet,
                talos_versions.get(node.ip, "?"),
            ]
            for node in nodes
        ],
    )


@cli.command()
@click.argument("node", required=False)
def disks(node: str | None):
    """Physical disk inventory from Talos. Omit NODE for all nodes.

    Filters out loop devices and Ceph RBD virtual devices.
    """
    nodes = get_all()
    targets = (
        [(n.name, n.ip) for n in nodes] if node is None else [(node, resolve_ip(node))]
    )
    rows = []
    for name, ip in targets:
        items = run_jsonl(
            ["talosctl", "get", "disks", "-o", "json", "-n", ip],
            timeout=15,
        )
        for item in items:
            spec = item.get("spec", {})
            dev = spec.get("dev_path", item.get("metadata", {}).get("id", ""))
            # Skip non-physical devices
            if "/loop" in dev or "/rbd" in dev:
                continue
            size = spec.get("pretty_size", human_bytes(spec.get("size", 0)))
            transport = spec.get("transport", "").upper()
            model = spec.get("model", "")
            # Role: sda is always Talos system, nvme0n1 is always Ceph OSD
            role = ""
            if "sda" in dev:
                role = "system"
            elif "nvme0n1" in dev:
                role = "ceph-osd"
            rows.append([name, dev, size, transport, model, role])
    table(["NODE", "DEVICE", "SIZE", "TRANSPORT", "MODEL", "ROLE"], rows)


@cli.command("audit-logs")
@click.argument("node", required=False)
def audit_logs(node: str | None) -> None:
    """Audit-log ownership and permissions on control-plane nodes."""
    nodes = get_all()
    targets = (
        [(item.name, item.ip) for item in nodes if item.role == "cp"]
        if node is None
        else [(node, resolve_ip(node))]
    )
    rows = []
    for name, ip in targets:
        result = run(
            ["talosctl", "ls", "/var/log/audit/kube", "-l", "-n", ip],
            timeout=15,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip().splitlines()[0]
            click.echo(f"error: talosctl failed for {name}: {message}", err=True)
            raise SystemExit(1)
        entries = [line.split() for line in result.stdout.splitlines()[1:]]
        directory = next((entry for entry in entries if entry[-1] == "."), None)
        active = next(
            (entry for entry in entries if entry[-1] == "kube-apiserver.log"),
            None,
        )
        if directory is None or active is None:
            rows.append([name, "missing", "-", "-", "-", "no"])
            continue
        files = [entry for entry in entries if entry[-1] != "."]
        total_size = sum(int(entry[4]) for entry in files)
        group_zero = (
            directory[3] == "0"
            and directory[1][6] == "x"
            and active[3] == "0"
            and active[1][4] == "r"
        )
        rows.append(
            [
                name,
                f"{directory[2]}:{directory[3]}",
                directory[1],
                active[1],
                f"{len(files)} / {human_bytes(total_size)}",
                "yes" if group_zero else "no",
            ]
        )
    table(["NODE", "OWNER", "DIR", "FILE", "FILES/SIZE", "GROUP 0"], rows)


@cli.command()
@click.argument("node")
def etcd(node: str) -> None:
    """Correlate local etcd service, cluster status, membership, and warnings."""
    target = next(
        (item for item in get_all() if item.name == node or item.ip == node),
        None,
    )
    if target is None:
        click.echo(f"error: node {node!r} not found", err=True)
        raise SystemExit(1)
    if target.role != "cp":
        click.echo(f"error: node {target.name!r} is not a control-plane node", err=True)
        raise SystemExit(1)
    ip = target.ip
    commands = {
        "LOCAL SERVICE": ["talosctl", "service", "etcd", "-n", ip],
        "CLUSTER STATUS": ["talosctl", "etcd", "status", "-n", ip],
        "MEMBERS": ["talosctl", "etcd", "members", "-n", ip],
    }
    failed = False
    for heading, command in commands.items():
        result = run(command, timeout=20, check=False)
        section(heading)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "talosctl failed").strip()
            click.echo(f"error: {message.splitlines()[0]}", err=True)
            failed = True
            continue
        click.echo(result.stdout.strip())

    logs = run(
        ["talosctl", "logs", "etcd", "-n", ip, "--tail", "100"],
        timeout=20,
        check=False,
    )
    section("RECENT WARNINGS")
    if logs.returncode != 0:
        message = (logs.stderr or logs.stdout or "talosctl failed").strip()
        click.echo(f"error: {message.splitlines()[0]}", err=True)
        raise SystemExit(1)
    warnings = []
    for line in logs.stdout.splitlines():
        payload = line.split(": ", 1)[-1]
        try:
            entry = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if entry.get("level") not in {"warn", "error", "fatal"}:
            continue
        warnings.append(
            [entry.get("ts", "?"), entry.get("level", "?"), entry.get("msg", "?")]
        )
    if warnings:
        table(["TIME", "LEVEL", "MESSAGE"], warnings[-20:])
    else:
        click.echo("(none)")
    if failed:
        raise SystemExit(1)


def _issue_lines(output: str, limit: int = 8) -> list[str]:
    lines = []
    seen = set()
    for line in reversed(output.splitlines()):
        normalized = re.sub(r'"ts":\d+(?:\.\d+)?', '"ts":?', line)
        normalized = re.sub(r"\d+m\d+(?:\.\d+)?s", "?", normalized)
        normalized = re.sub(r"[0-9a-f]{32,}", "<id>", normalized)
        normalized = re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27,}", "<id>", normalized)
        if not any(term in normalized.lower() for term in _ISSUE_TERMS):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        lines.append(line)
        if len(lines) == limit:
            break
    return list(reversed(lines))


@cli.command()
@click.argument("node")
def diagnose(node: str) -> None:
    """Correlate Kubernetes state, Talos services, and recent runtime errors."""
    ip = resolve_ip(node)
    data = run_json(["kubectl", "get", "node", node, "-o", "json"], timeout=15)
    conditions = data.get("status", {}).get("conditions", [])

    section("KUBERNETES CONDITIONS")
    rows = []
    for condition in conditions:
        rows.append(
            [
                condition.get("type", "?"),
                condition.get("status", "?"),
                condition.get("reason", "?"),
                condition.get("message", "?"),
            ]
        )
    table(["CONDITION", "STATUS", "REASON", "MESSAGE"], rows)

    services = run(["talosctl", "services", "-n", ip], timeout=15)
    section("TALOS SERVICES")
    if services.returncode != 0:
        message = (services.stderr or services.stdout or "talosctl failed").strip()
        click.echo(f"error: {message.splitlines()[0]}", err=True)
        raise SystemExit(1)
    click.echo(services.stdout.strip())

    failed_services = []
    for line in services.stdout.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 4 and (fields[2] != "Running" or fields[3] == "Fail"):
            failed_services.append(fields[1])

    log_services = list(dict.fromkeys([*failed_services, "kubelet"]))
    issues = []
    for service in log_services:
        result = run(
            ["talosctl", "logs", service, "-n", ip, "--tail", "150"],
            timeout=20,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip().splitlines()[0]
            issues.append(f"{service}: {message}")
            continue
        issues.extend(_issue_lines(result.stdout))

    section("RECENT RUNTIME ISSUES")
    click.echo("\n".join(issues[-12:]) if issues else "(none)")


@cli.command()
@click.argument("node", required=False)
def status(node: str | None):
    """Node conditions and resource pressure. Omit NODE for all nodes."""
    data = kubectl_json("nodes")
    items = data.get("items", [])
    if node:
        items = [
            i
            for i in items
            if i["metadata"]["name"] == node
            or any(
                a["address"] == node for a in i.get("status", {}).get("addresses", [])
            )
        ]
        if not items:
            click.echo(f"error: node {node!r} not found")
            raise SystemExit(1)

    for item in items:
        name = item["metadata"]["name"]
        st = item.get("status", {})
        section(name)

        # Conditions
        conds = st.get("conditions", [])
        cond_rows = []
        for c in conds:
            ctype = c.get("type", "")
            cstatus = c.get("status", "")
            flag = (
                "OK"
                if (
                    (ctype == "Ready" and cstatus == "True")
                    or (ctype != "Ready" and cstatus == "False")
                )
                else "PROBLEM"
            )
            cond_rows.append([ctype, cstatus, flag])
        table(["CONDITION", "STATUS", ""], cond_rows)

        # Resource summary
        alloc = st.get("allocatable", {})
        cap = st.get("capacity", {})
        pairs = []
        if "cpu" in alloc:
            pairs.append(
                ("CPU", f"{alloc['cpu']} allocatable / {cap.get('cpu', '?')} capacity")
            )
        if "memory" in alloc:
            pairs.append(
                (
                    "Memory",
                    f"{alloc['memory']} allocatable / {cap.get('memory', '?')} capacity",
                )
            )
        if "ephemeral-storage" in alloc:
            pairs.append(("Ephemeral", f"{alloc['ephemeral-storage']} allocatable"))
        if pairs:
            click.echo()
            kv(pairs, indent=2)

        # Top pods by resource on this node
        try:
            # Get all pods on this node
            pods_data = run_json(
                [
                    "kubectl",
                    "get",
                    "pods",
                    "--all-namespaces",
                    "--field-selector",
                    f"spec.nodeName={name}",
                    "-o",
                    "json",
                ],
                timeout=15,
            )
            pod_names = {
                f"{p['metadata']['namespace']}/{p['metadata']['name']}"
                for p in pods_data.get("items", [])
            }

            # Get top output
            result = run(
                ["kubectl", "top", "pods", "--all-namespaces", "--no-headers"],
                timeout=15,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                top_rows = []
                for line in result.stdout.strip().split("\n"):
                    parts = line.split()
                    if len(parts) >= 4:
                        ns, pname, cpu, mem = parts[0], parts[1], parts[2], parts[3]
                        if f"{ns}/{pname}" in pod_names:
                            top_rows.append((ns, pname, cpu, mem))

                # Sort by memory (parse Mi/Gi suffix)
                def mem_sort_key(row):
                    m = row[3]
                    try:
                        if m.endswith("Gi"):
                            return float(m[:-2]) * 1024
                        if m.endswith("Mi"):
                            return float(m[:-2])
                        return float(m)
                    except ValueError:
                        return 0

                top_rows.sort(key=mem_sort_key, reverse=True)
                if top_rows:
                    click.echo()
                    click.echo("  Top pods by memory:")
                    table(
                        ["  POD", "CPU", "MEMORY"],
                        [
                            [f"  {ns}/{pname}", cpu, mem]
                            for ns, pname, cpu, mem in top_rows[:5]
                        ],
                    )
        except SystemExit:
            pass
