"""Storage domain: Ceph, PVCs, and disk management."""

from __future__ import annotations

import click

from hops._click import HelpfulGroup
from hops.core.format import human_bytes, info, kv, section, table
from hops.core.nodes import resolve_ip
from hops.core.runner import ceph_json, kubectl_json, run
from hops.core.workload import resolve_pods


@click.group(cls=HelpfulGroup)
def cli():
    """Cluster storage: Ceph, PVCs, disks."""


# -- Ceph subgroup --


@cli.group(cls=HelpfulGroup)
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


def _selinux_context(spec: dict) -> str:
    """Format SELinux options from a pod or container security context."""
    options = spec.get("securityContext", {}).get("seLinuxOptions", {})
    if not options:
        return "unset"
    return ",".join(f"{key}={value}" for key, value in sorted(options.items()))


def _selinux_host_mount(daemonset: dict) -> str:
    """Summarize whether a CSI node plugin mounts the host SELinux policy."""
    spec = daemonset.get("spec", {}).get("template", {}).get("spec", {})
    host_volumes = {
        volume.get("name", "")
        for volume in spec.get("volumes", [])
        if volume.get("hostPath", {}).get("path") == "/etc/selinux"
    }
    if not host_volumes:
        return "absent"

    for container in spec.get("containers", []):
        for mount in container.get("volumeMounts", []):
            if mount.get("name") in host_volumes:
                read_only = "ro" if mount.get("readOnly") else "rw"
                return f"{mount.get('mountPath', '?')} ({read_only})"
    return "volume only"


def _security_identity(spec: dict, fallback: dict | None = None) -> str:
    """Format the effective runtime identity from a security context."""
    context = spec.get("securityContext", {})
    fallback = fallback or {}
    values = {
        "uid": context.get("runAsUser", fallback.get("runAsUser", "?")),
        "gid": context.get("runAsGroup", fallback.get("runAsGroup", "?")),
        "nonroot": context.get("runAsNonRoot", fallback.get("runAsNonRoot", "?")),
    }
    return ",".join(f"{key}={value}" for key, value in values.items())


@cli.command("selinux")
@click.argument("app")
@click.option("-n", "--namespace", default=None, help="Namespace filter")
def selinux_volume(app: str, namespace: str | None) -> None:
    """Correlate an app's SELinux context with its CSI volume contract."""
    resolved = resolve_pods(app, namespace)
    if not resolved:
        click.echo(f"error: app {app!r} not found", err=True)
        raise SystemExit(1)

    ns, pods = resolved
    pod = pods[0]
    pod_name = pod.get("metadata", {}).get("name", "?")
    pod_spec = pod.get("spec", {})
    node_name = pod_spec.get("nodeName", "?")
    pod_security = pod_spec.get("securityContext", {})
    container_contexts = [
        f"{container.get('name', '?')}={_selinux_context(container)}"
        for container in pod_spec.get("containers", [])
    ]
    container_identities = [
        f"{container.get('name', '?')}={_security_identity(container, pod_security)}"
        for container in pod_spec.get("containers", [])
    ]
    kv(
        [
            ("pod", f"{ns}/{pod_name}"),
            ("node", node_name),
            ("pod identity", _security_identity(pod_spec)),
            ("fsGroup", pod_security.get("fsGroup", "?")),
            ("container identity", ", ".join(container_identities) or "none"),
            ("pod SELinux", _selinux_context(pod_spec)),
            ("container SELinux", ", ".join(container_contexts) or "none"),
            (
                "change policy",
                pod_spec.get("securityContext", {}).get("seLinuxChangePolicy", "unset"),
            ),
        ]
    )

    host_rows = []
    for volume in pod_spec.get("volumes", []):
        host_path = volume.get("hostPath", {}).get("path")
        if not host_path:
            continue
        mounts = []
        for container in pod_spec.get("containers", []):
            for mount in container.get("volumeMounts", []):
                if mount.get("name") != volume.get("name"):
                    continue
                mode = "ro" if mount.get("readOnly") else "rw"
                mounts.append(
                    f"{container.get('name', '?')}:{mount.get('mountPath', '?')}:{mode}"
                )
        host_rows.append(
            [volume.get("name", "?"), host_path, ",".join(mounts) or "unmounted"]
        )
    if host_rows:
        section("HOST VOLUMES")
        table(["VOLUME", "HOST PATH", "CONTAINER:MOUNT:MODE"], host_rows)

    result = run(["talosctl", "dmesg", "-n", resolve_ip(node_name)], timeout=15)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip().splitlines()[0]
        click.echo(f"error: talosctl failed for {node_name}: {message}", err=True)
        raise SystemExit(1)
    denials = [line for line in result.stdout.splitlines() if "avc:  denied" in line]
    section("SELINUX AVC DENIALS")
    if denials:
        for line in denials[-10:]:
            click.echo(line)
    else:
        click.echo("None found.")

    pv_data = kubectl_json("pv")
    pv_map = {item["metadata"]["name"]: item for item in pv_data.get("items", [])}
    sc_data = kubectl_json("storageclasses")
    sc_map = {item["metadata"]["name"]: item for item in sc_data.get("items", [])}
    drivers = kubectl_json("csidrivers")
    driver_map = {item["metadata"]["name"]: item for item in drivers.get("items", [])}

    rows = []
    used_drivers: set[str] = set()
    for volume in pod_spec.get("volumes", []):
        claim = volume.get("persistentVolumeClaim", {}).get("claimName")
        if not claim:
            continue
        pvc = kubectl_json(f"pvc/{claim}", namespace=ns)
        pvc_spec = pvc.get("spec", {})
        pv = pv_map.get(pvc_spec.get("volumeName", ""), {})
        pv_spec = pv.get("spec", {})
        csi = pv_spec.get("csi", {})
        driver = csi.get("driver", "?")
        used_drivers.add(driver)
        sc = sc_map.get(pvc_spec.get("storageClassName", ""), {})
        mount_options = sc.get("mountOptions", [])
        rows.append(
            [
                volume.get("name", "?"),
                claim,
                ",".join(pvc_spec.get("accessModes", [])) or "?",
                pvc_spec.get("storageClassName", "?"),
                driver,
                csi.get("fsType", "?"),
                ",".join(mount_options) or "none",
            ]
        )

    info("")
    table(
        ["VOLUME", "PVC", "ACCESS", "CLASS", "DRIVER", "FS", "MOUNT OPTIONS"],
        rows,
    )

    info("")
    for driver in sorted(used_drivers):
        csi_driver = driver_map.get(driver, {}).get("spec", {})
        kv(
            [
                ("CSI driver", driver),
                ("seLinuxMount", str(csi_driver.get("seLinuxMount", "unset"))),
                ("fsGroupPolicy", csi_driver.get("fsGroupPolicy", "unset")),
            ]
        )

    daemonsets = kubectl_json("daemonsets")
    for daemonset in daemonsets.get("items", []):
        template = daemonset.get("spec", {}).get("template", {}).get("spec", {})
        text = str(template)
        if not any(driver in text for driver in used_drivers):
            continue
        metadata = daemonset.get("metadata", {})
        info("")
        kv(
            [
                (
                    "node plugin",
                    f"{metadata.get('namespace', '?')}/{metadata.get('name', '?')}",
                ),
                ("host SELinux", _selinux_host_mount(daemonset)),
            ]
        )
