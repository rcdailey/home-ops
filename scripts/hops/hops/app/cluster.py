"""Cluster-wide app commands: listing, health, events, and secrets."""

from __future__ import annotations

import click

from hops.app import cli
from hops.core.format import age_str, info, section, table, truncate
from hops.core.runner import kubectl_json, run, run_json
from hops.core.workload import resolve_app, suggest_near_matches

# Namespaces to skip in list/events when no namespace is specified
_SYSTEM_NS = frozenset(
    {
        "kube-system",
        "kube-node-lease",
        "kube-public",
        "rook-ceph",
        "flux-system",
    }
)


@cli.command("list")
@click.argument("namespace", required=False)
def list_apps(namespace: str | None):
    """Running workloads (Deployments, StatefulSets, DaemonSets, CronJobs)."""
    rows = []
    kind_labels = {
        "deployments": "D",
        "statefulsets": "S",
        "daemonsets": "DS",
        "cronjobs": "CJ",
    }
    for kind in kind_labels:
        data = kubectl_json(kind, namespace=namespace)
        for item in data.get("items", []):
            meta = item.get("metadata", {})
            ns = meta.get("namespace", "")
            if not namespace and ns in _SYSTEM_NS:
                continue
            name = meta.get("name", "")
            status = item.get("status", {})
            k = kind_labels[kind]

            if kind == "cronjobs":
                active = len(status.get("active", []))
                suspended = item.get("spec", {}).get("suspend", False)
                ready_str = "suspended" if suspended else f"{active} active"
            else:
                ready = status.get("readyReplicas", 0) or 0
                desired = (
                    status.get("replicas", 0)
                    or item.get("spec", {}).get("replicas", 0)
                    or 0
                )
                ready_str = f"{ready}/{desired}"

            age_val = age_str(meta.get("creationTimestamp"))
            rows.append([ns, name, k, ready_str, age_val])

    rows.sort(key=lambda r: (r[0], r[1]))
    table(["NAMESPACE", "NAME", "KIND", "READY", "AGE"], rows)


@cli.command()
@click.argument("namespace", required=False)
def unhealthy(namespace: str | None):
    """Pods not Running/Succeeded cluster-wide (or in a namespace).

    Quick cluster health check: shows pods stuck in Pending,
    ContainerCreating, CrashLoopBackOff, Error, etc. Excludes system
    namespaces unless a namespace is specified. Returns a one-liner when
    all pods are healthy.
    """
    data = kubectl_json("pods", namespace=namespace)
    rows = []
    for item in data.get("items", []):
        meta = item.get("metadata", {})
        ns = meta.get("namespace", "")
        if not namespace and ns in _SYSTEM_NS:
            continue
        status = item.get("status", {})
        phase = status.get("phase", "Unknown")
        if phase in ("Running", "Succeeded"):
            continue
        name = meta.get("name", "")
        # Derive status reason from container statuses (more specific than phase)
        reason = phase
        for cs in status.get("containerStatuses", []) + status.get(
            "initContainerStatuses", []
        ):
            state = cs.get("state", {})
            if "waiting" in state:
                reason = state["waiting"].get("reason", reason)
                break
            if "terminated" in state:
                reason = state["terminated"].get("reason", reason)
                break
        age_val = age_str(meta.get("creationTimestamp"))
        rows.append([ns, name, reason, age_val])
    if not rows:
        scope = f"in {namespace}" if namespace else "cluster-wide"
        info(f"All pods healthy {scope}.")
        return
    rows.sort(key=lambda r: (r[0], r[1]))
    table(["NAMESPACE", "POD", "STATUS", "AGE"], rows)


@cli.command()
@click.argument("namespace", required=False)
@click.option("--all", "show_all", is_flag=True, help="Include Normal events")
@click.option("--limit", default=50, help="Max events to show")
def events(namespace: str | None, show_all: bool, limit: int):
    """Kubernetes events (non-Normal by default)."""
    args = ["kubectl", "get", "events", "--sort-by=.lastTimestamp", "-o", "json"]
    if namespace:
        args.extend(["-n", namespace])
    else:
        args.append("--all-namespaces")
    data = run_json(args, timeout=30)
    items = data.get("items", [])

    if not show_all:
        items = [e for e in items if e.get("type", "Normal") != "Normal"]
    if not namespace:
        items = [
            e
            for e in items
            if e.get("metadata", {}).get("namespace", "") not in _SYSTEM_NS
        ]

    items = items[-limit:]

    if not items:
        info("No events found." if show_all else "No non-Normal events found.")
        return

    rows = []
    for e in items:
        meta = e.get("metadata", {})
        ns = meta.get("namespace", "")
        etype = e.get("type", "?")
        reason = e.get("reason", "?")
        obj_ref = e.get("involvedObject", {})
        obj = f"{obj_ref.get('kind', '?')}/{obj_ref.get('name', '?')}"
        msg = truncate(e.get("message", ""), 120)
        last_seen = age_str(e.get("lastTimestamp"))
        count = e.get("count", 1)
        count_str = f"x{count}" if count > 1 else ""
        rows.append([last_seen, ns, etype, reason, obj, count_str, msg])

    table(["AGE", "NS", "TYPE", "REASON", "OBJECT", "#", "MESSAGE"], rows)


@cli.command()
@click.argument("namespace", required=False)
def secrets(namespace: str | None):
    """ExternalSecret sync status."""
    args = ["kubectl", "get", "externalsecrets", "-o", "json"]
    if namespace:
        args.extend(["-n", namespace])
    else:
        args.append("--all-namespaces")
    data = run_json(args, timeout=30)

    rows = []
    for item in data.get("items", []):
        meta = item.get("metadata", {})
        ns = meta.get("namespace", "")
        name = meta.get("name", "")
        status = item.get("status", {})
        conditions = status.get("conditions", [])

        sync_status = "?"
        message = ""
        for cond in conditions:
            if cond.get("type") == "Ready":
                sync_status = "Synced" if cond.get("status") == "True" else "Error"
                if sync_status == "Error":
                    message = truncate(cond.get("message", ""), 80)
                break

        refresh = status.get("refreshTime")
        age_val = age_str(refresh) if refresh else "?"
        row = [ns, name, sync_status, age_val]
        if message:
            row.append(message)
        rows.append(row)

    rows.sort(key=lambda r: (r[0], r[1]))
    headers = ["NAMESPACE", "NAME", "STATUS", "LAST SYNC"]
    if any(len(r) > 4 for r in rows):
        headers.append("MESSAGE")
        for r in rows:
            if len(r) == 4:
                r.append("")
    table(headers, rows)


@cli.command()
@click.argument("app")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (auto-detected if omitted)"
)
def resources(app: str, namespace: str | None):
    """Pod resource usage vs requests/limits for an app."""
    wl = resolve_app(app, namespace)
    if not wl:
        hints = suggest_near_matches(app, namespace)
        info(f"error: could not find app {app!r}")
        if hints:
            info(f"  similar: {', '.join(hints)}")
        raise SystemExit(1)

    spec_data = kubectl_json("pods", namespace=wl.namespace)
    pod_specs: dict[str, list[dict]] = {}
    for item in spec_data.get("items", []):
        name = item["metadata"]["name"]
        if name.startswith(wl.name):
            pod_specs[name] = item.get("spec", {}).get("containers", [])

    if not pod_specs:
        info(f"No pods found for {wl.name!r} in {wl.namespace}")
        return

    usage_map: dict[str, dict[str, dict]] = {}
    try:
        result = run(
            [
                "kubectl",
                "top",
                "pods",
                "-n",
                wl.namespace,
                "--no-headers",
                "--containers",
            ],
            timeout=15,
            check=False,
        )
        if result.returncode == 0 and result.stdout:
            for line in result.stdout.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 4:
                    pname, cname, cpu, mem = parts[0], parts[1], parts[2], parts[3]
                    if pname.startswith(wl.name):
                        usage_map.setdefault(pname, {})[cname] = {
                            "cpu": cpu,
                            "memory": mem,
                        }
    except SystemExit:
        pass

    rows = []
    for pod_name in sorted(pod_specs):
        for container in pod_specs[pod_name]:
            cname = container.get("name", "")
            res = container.get("resources", {})
            req = res.get("requests", {})
            lim = res.get("limits", {})
            usage = usage_map.get(pod_name, {}).get(cname, {})
            rows.append(
                [
                    pod_name,
                    cname,
                    usage.get("cpu", "-"),
                    req.get("cpu", "-"),
                    lim.get("cpu", "-"),
                    usage.get("memory", "-"),
                    req.get("memory", "-"),
                    lim.get("memory", "-"),
                ]
            )

    table(
        [
            "POD",
            "CONTAINER",
            "CPU.use",
            "CPU.req",
            "CPU.lim",
            "MEM.use",
            "MEM.req",
            "MEM.lim",
        ],
        rows,
    )


@cli.command()
def types():
    """List every resolvable resource category with a sample name.

    Shows one example from each category the resolver can target.
    Doubles as a smoke test and self-documentation for what hops
    can resolve.
    """
    categories = [
        ("Deployment", "deployments"),
        ("StatefulSet", "statefulsets"),
        ("DaemonSet", "daemonsets"),
        ("CronJob", "cronjobs"),
        ("Job", "jobs"),
    ]

    section("WORKLOADS")
    rows = []
    for label, kind in categories:
        data = kubectl_json(kind)
        items = data.get("items", [])
        items = [
            i
            for i in items
            if i.get("metadata", {}).get("namespace", "") not in _SYSTEM_NS
        ]
        sample = items[0]["metadata"]["name"] if items else "(none)"
        ns = items[0]["metadata"]["namespace"] if items else ""
        rows.append([label, str(len(items)), sample, ns])
    table(["KIND", "COUNT", "SAMPLE", "NAMESPACE"], rows)

    section("GATEWAY-ONLY")
    gw_rows = []
    for kind, label in [
        ("backends.gateway.envoyproxy.io", "Backend"),
        ("httproutes", "HTTPRoute"),
    ]:
        try:
            data = run_json(
                ["kubectl", "get", kind, "-A", "-o", "json"],
                timeout=10,
            )
            items = data.get("items", [])
            sample = items[0]["metadata"]["name"] if items else "(none)"
            ns = items[0]["metadata"]["namespace"] if items else ""
            gw_rows.append([label, str(len(items)), sample, ns])
        except SystemExit:
            gw_rows.append([label, "0", "(unavailable)", ""])
    table(["KIND", "COUNT", "SAMPLE", "NAMESPACE"], gw_rows)

    section("OPERATOR-MANAGED")
    op_rows = []
    for kind, label in [
        ("cluster.postgresql.cnpg.io", "CNPG Cluster"),
        ("mariadb.k8s.mariadb.com", "MariaDB"),
    ]:
        try:
            data = run_json(
                ["kubectl", "get", kind, "-A", "-o", "json"],
                timeout=10,
            )
            items = data.get("items", [])
            sample = items[0]["metadata"]["name"] if items else "(none)"
            ns = items[0]["metadata"]["namespace"] if items else ""
            op_rows.append([label, str(len(items)), sample, ns])
        except SystemExit:
            op_rows.append([label, "0", "(unavailable)", ""])
    table(["KIND", "COUNT", "SAMPLE", "NAMESPACE"], op_rows)
