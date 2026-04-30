"""Storage domain: Ceph, PVCs, and disk management."""

from __future__ import annotations

import click

from hops._format import human_bytes, info, kv, table
from hops._runner import ceph_json, kubectl_json


@click.group()
def cli():
    """Cluster storage: Ceph, PVCs, disks."""


# -- Ceph subgroup --


@cli.group()
def ceph():
    """Rook Ceph storage cluster."""


@ceph.command("status")
def ceph_status():
    """Compact Ceph health, PG, OSD, and capacity summary."""
    data = ceph_json(["status"])

    health = data.get("health", {})
    health_status = health.get("status", "UNKNOWN")
    info(f"HEALTH: {health_status}")

    # Health checks (warnings/errors)
    checks = health.get("checks", {})
    if checks:
        for name, detail in checks.items():
            severity = detail.get("severity", "")
            msg = detail.get("summary", {}).get("message", "")
            info(f"  [{severity}] {name}: {msg}")

    # PG summary
    pgmap = data.get("pgmap", {})
    pgs_by_state = pgmap.get("pgs_by_state", [])
    total_pgs = pgmap.get("num_pgs", 0)
    pg_parts = []
    for entry in pgs_by_state:
        pg_parts.append(f"{entry.get('count', 0)} {entry.get('state_name', '?')}")
    if pg_parts:
        info(f"  PGs: {', '.join(pg_parts)} ({total_pgs} total)")

    # OSD summary
    osdmap = data.get("osdmap", {})
    num_osds = osdmap.get("num_osds", 0)
    num_up = osdmap.get("num_up_osds", 0)
    num_in = osdmap.get("num_in_osds", 0)
    info(f"  OSDs: {num_up} up, {num_in} in (of {num_osds})")

    # Capacity
    bytes_used = pgmap.get("bytes_used", 0)
    bytes_total = pgmap.get("bytes_total", 0)
    pct = (bytes_used / bytes_total * 100) if bytes_total else 0
    info(
        f"  Capacity: {human_bytes(bytes_used)} / {human_bytes(bytes_total)} ({pct:.1f}%)"
    )

    # Objects
    num_objects = pgmap.get("num_objects", 0)
    info(f"  Objects: {num_objects:,}")


@ceph.command("osd")
def ceph_osd():
    """OSD table: id, node, status, usage, latency."""
    # OSD tree for node mapping
    tree = ceph_json(["osd", "tree"])
    node_map: dict[int, str] = {}
    for node in tree.get("nodes", []):
        if node.get("type") == "host":
            hostname = node.get("name", "")
            for child_id in node.get("children", []):
                node_map[child_id] = hostname

    # OSD dump for status
    dump = ceph_json(["osd", "dump"])
    osd_status: dict[int, dict] = {}
    for osd in dump.get("osds", []):
        osd_status[osd["osd"]] = osd

    # OSD df for usage
    df = ceph_json(["osd", "df"])
    rows = []
    for node in df.get("nodes", []):
        osd_id = node.get("id", -1)
        hostname = node_map.get(osd_id, "?")
        st = osd_status.get(osd_id, {})
        up = "up" if st.get("up", 0) else "DOWN"
        in_cluster = "in" if st.get("in", 0) else "OUT"
        status_str = f"{up}/{in_cluster}"
        kb_used = node.get("kb_used", 0) * 1024
        kb_total = (node.get("kb", 0) or 1) * 1024
        pct = node.get("utilization", 0)
        size_str = human_bytes(kb_total)
        used_str = human_bytes(kb_used)
        pct_str = f"{pct:.1f}%"
        # Flag high usage
        if pct > 80:
            pct_str += " (!)"
        rows.append(
            [
                str(osd_id),
                hostname,
                status_str,
                f"{used_str}/{size_str}",
                pct_str,
            ]
        )

    rows.sort(key=lambda r: int(r[0]))
    table(["OSD", "NODE", "STATUS", "USED/TOTAL", "USE%"], rows)


@ceph.command("io")
def ceph_io():
    """Current I/O rates and recovery/scrub progress."""
    data = ceph_json(["status"])
    pgmap = data.get("pgmap", {})

    # I/O rates
    read_bps = pgmap.get("read_bytes_sec", 0)
    write_bps = pgmap.get("write_bytes_sec", 0)
    read_iops = pgmap.get("read_op_per_sec", 0)
    write_iops = pgmap.get("write_op_per_sec", 0)

    pairs = [
        ("Read", f"{human_bytes(read_bps)}/s ({read_iops} IOPS)"),
        ("Write", f"{human_bytes(write_bps)}/s ({write_iops} IOPS)"),
    ]

    # Recovery progress
    recovering = pgmap.get("recovering_objects_per_sec", 0)
    recovering_bps = pgmap.get("recovering_bytes_per_sec", 0)
    if recovering or recovering_bps:
        pairs.append(
            (
                "Recovery",
                f"{recovering} obj/s, {human_bytes(recovering_bps)}/s",
            )
        )

    kv(pairs)

    # Scrub status from PG states
    pgs_by_state = pgmap.get("pgs_by_state", [])
    scrub_states = [s for s in pgs_by_state if "scrub" in s.get("state_name", "")]
    if scrub_states:
        for s in scrub_states:
            info(f"  Scrub: {s['count']} PGs in {s['state_name']}")
    else:
        info("  Scrub: none active")


# -- PVC command --


def _pv_driver(pv: dict) -> str:
    """Extract the storage driver from a PV (CSI driver or local-volume)."""
    spec = pv.get("spec", {})
    csi = spec.get("csi", {})
    if csi:
        driver = csi.get("driver", "")
        # Shorten well-known drivers for table readability
        if "rbd" in driver:
            return "rbd"
        if "cephfs" in driver:
            return "cephfs"
        if "nfs" in driver:
            return "nfs"
        return driver
    if spec.get("local"):
        return "local"
    if spec.get("hostPath"):
        return "hostpath"
    if spec.get("nfs"):
        return "nfs"
    return "?"


@cli.command()
@click.argument("app_or_ns", required=False)
@click.option("-n", "--namespace", default=None, help="Namespace filter")
@click.option("--problems", is_flag=True, help="Show only Lost/Pending PVCs")
def pvcs(app_or_ns: str | None, namespace: str | None, problems: bool):
    """PVC status with PV backing driver and health.

    Correlates each PVC with its bound PV to show the actual storage
    driver (rbd, cephfs, local, nfs). Flags Lost and Pending PVCs.

    Optional positional argument filters by app name (substring match
    on PVC name) or namespace.
    """
    # Resolve positional arg as namespace or app filter
    app_filter: str | None = None
    if app_or_ns and not namespace:
        # If it looks like a namespace (exists in PVC data), treat as namespace
        # Otherwise treat as app name filter
        probe = kubectl_json("namespaces")
        ns_names = {i["metadata"]["name"] for i in probe.get("items", [])}
        if app_or_ns in ns_names:
            namespace = app_or_ns
        else:
            app_filter = app_or_ns
    elif app_or_ns:
        app_filter = app_or_ns

    pvc_data = kubectl_json("pvc", namespace=namespace)

    # Build PV lookup map (name -> PV object)
    pv_data = kubectl_json("pv")
    pv_map: dict[str, dict] = {}
    for pv in pv_data.get("items", []):
        pv_map[pv["metadata"]["name"]] = pv

    rows = []
    has_problems = False
    for item in pvc_data.get("items", []):
        meta = item.get("metadata", {})
        spec = item.get("spec", {})
        status = item.get("status", {})
        ns = meta.get("namespace", "")
        name = meta.get("name", "")
        phase = status.get("phase", "?")
        cap = status.get("capacity", {}).get("storage", "?")
        sc = spec.get("storageClassName", "?")
        pv_name = spec.get("volumeName", "")

        # App filter: substring match on PVC name
        if app_filter and app_filter.lower() not in name.lower():
            continue

        # Determine driver from bound PV
        pv = pv_map.get(pv_name)
        if pv:
            driver = _pv_driver(pv)
        elif pv_name:
            driver = "LOST"
            has_problems = True
        else:
            driver = "-"

        # Flag problems
        flag = ""
        if phase == "Lost" or driver == "LOST":
            flag = "(!)"
            has_problems = True
        elif phase == "Pending":
            flag = "(?)"
            has_problems = True

        if problems and not flag:
            continue

        phase_str = f"{phase} {flag}".strip()
        rows.append([ns, name, phase_str, cap, sc, driver])

    rows.sort(key=lambda r: (r[0], r[1]))
    table(["NAMESPACE", "NAME", "STATUS", "CAPACITY", "CLASS", "DRIVER"], rows)

    if has_problems:
        info("")
        info("(!) = PV lost or missing; (?) = PVC pending, not yet bound")
