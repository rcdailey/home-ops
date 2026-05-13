"""CloudNativePG database cluster overview.

Correlates CNPG Cluster CRs, pods, PDBs, PVCs, and resource usage
into a single view. Replaces the multi-kubectl sequence needed to
audit database health, replica placement, and backup status.
"""

from __future__ import annotations

import click

from hops._format import age_str, info, kv, section, table
from hops._runner import kubectl_json, run


@click.group("db", no_args_is_help=True)
def cli():
    """CloudNativePG database operations."""


@cli.command("status")
def status_cmd():
    """Overview of all CNPG clusters: replicas, nodes, PDBs, backups, resources."""
    clusters_data = kubectl_json("cluster.postgresql.cnpg.io")
    clusters = clusters_data.get("items", [])
    if not clusters:
        info("No CNPG clusters found.")
        return

    # Fetch all CNPG-labeled pods, PVCs, and PDBs in one pass each
    pods_data = kubectl_json("pods", "-l", "cnpg.io/cluster")
    pvcs_data = kubectl_json("pvc", "-l", "cnpg.io/cluster")
    pdbs_data = kubectl_json("pdb", "-l", "cnpg.io/cluster")

    # Fetch actual memory usage via kubectl top
    top_result = run(
        ["kubectl", "top", "pods", "-A", "-l", "cnpg.io/cluster", "--no-headers"],
        timeout=15,
        check=False,
    )
    # Parse top output: NS NAME CPU MEM
    mem_actual: dict[str, str] = {}
    if top_result.returncode == 0 and top_result.stdout:
        for line in top_result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 4:
                mem_actual[f"{parts[0]}/{parts[1]}"] = parts[3]

    # Index pods by cluster
    pods_by_cluster: dict[str, list[dict]] = {}
    for pod in pods_data.get("items", []):
        cluster = pod["metadata"].get("labels", {}).get("cnpg.io/cluster", "")
        ns = pod["metadata"]["namespace"]
        key = f"{ns}/{cluster}"
        pods_by_cluster.setdefault(key, []).append(pod)

    # Index PVCs by cluster
    pvcs_by_cluster: dict[str, list[dict]] = {}
    for pvc in pvcs_data.get("items", []):
        cluster = pvc["metadata"].get("labels", {}).get("cnpg.io/cluster", "")
        ns = pvc["metadata"]["namespace"]
        key = f"{ns}/{cluster}"
        pvcs_by_cluster.setdefault(key, []).append(pvc)

    # Index PDBs by cluster
    pdbs_by_cluster: dict[str, dict] = {}
    for pdb in pdbs_data.get("items", []):
        cluster = pdb["metadata"].get("labels", {}).get("cnpg.io/cluster", "")
        ns = pdb["metadata"]["namespace"]
        key = f"{ns}/{cluster}"
        pdbs_by_cluster[key] = pdb

    for cluster in sorted(clusters, key=lambda c: c["metadata"]["name"]):
        meta = cluster["metadata"]
        spec = cluster.get("spec", {})
        cluster_status = cluster.get("status", {})
        cname = meta["name"]
        ns = meta["namespace"]
        key = f"{ns}/{cname}"

        section(f"{cname} ({ns})")

        # Basic info
        instances = spec.get("instances", 1)
        ready = cluster_status.get("readyInstances", 0)
        phase = cluster_status.get("phase", "?")
        has_backup = "backup" in spec or "barmanObjectStore" in spec.get("backup", {})

        pairs = [
            ("instances", f"{ready}/{instances} ready"),
            ("phase", phase),
            ("image", spec.get("imageName", "?")),
            ("storage", spec.get("storage", {}).get("size", "?")),
            ("backup", "yes" if has_backup else "no"),
        ]

        # PDB status
        pdb = pdbs_by_cluster.get(key)
        if pdb:
            allowed = pdb.get("status", {}).get("disruptionsAllowed", 0)
            pairs.append(("pdb", f"disruptionsAllowed={allowed}"))

        kv(pairs)

        # Pod placement and resource usage
        pods = pods_by_cluster.get(key, [])
        if pods:
            rows = []
            for pod in sorted(pods, key=lambda p: p["metadata"]["name"]):
                pname = pod["metadata"]["name"]
                node = pod.get("spec", {}).get("nodeName", "?")
                role = (
                    pod["metadata"].get("labels", {}).get("cnpg.io/instanceRole", "?")
                )
                pod_phase = pod.get("status", {}).get("phase", "?")

                # Memory: request, limit, actual
                containers = pod.get("spec", {}).get("containers", [])
                req_mem = "?"
                lim_mem = "?"
                if containers:
                    res = containers[0].get("resources", {})
                    req_mem = res.get("requests", {}).get("memory", "?")
                    lim_mem = res.get("limits", {}).get("memory", "?")
                actual = mem_actual.get(f"{ns}/{pname}", "?")

                rows.append([pname, role, node, pod_phase, req_mem, actual, lim_mem])
            table(
                ["POD", "ROLE", "NODE", "STATUS", "REQ", "ACTUAL", "LIMIT"],
                rows,
            )

        # PVC details
        pvcs = pvcs_by_cluster.get(key, [])
        if pvcs:
            pvc_rows = []
            for pvc in sorted(pvcs, key=lambda p: p["metadata"]["name"]):
                pvc_name = pvc["metadata"]["name"]
                size = (
                    pvc.get("spec", {})
                    .get("resources", {})
                    .get("requests", {})
                    .get("storage", "?")
                )
                pvc_phase = pvc.get("status", {}).get("phase", "?")
                sc = pvc.get("spec", {}).get("storageClassName", "?")
                pvc_rows.append([pvc_name, size, sc, pvc_phase])
            table(["PVC", "SIZE", "CLASS", "STATUS"], pvc_rows)

        # Last backup time
        last_backup = cluster_status.get("lastSuccessfulBackup")
        if last_backup:
            info(f"last backup: {age_str(last_backup)} ago")
