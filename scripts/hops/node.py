"""Node domain: cluster node information and diagnostics."""

from __future__ import annotations


import click

from hops._format import human_bytes, kv, section, table
from hops._nodes import get_all, resolve_ip
from hops._runner import kubectl_json, run, run_json, run_jsonl


@click.group()
def cli():
    """Cluster node information and diagnostics."""


@cli.command("list")
def list_nodes():
    """Compact table of all cluster nodes."""
    nodes = get_all()
    table(
        ["NODE", "IP", "ROLE", "STATUS", "KUBELET"],
        [[n.name, n.ip, n.role, n.status, n.kubelet] for n in nodes],
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
