"""App domain: application listing, debugging, and diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone

import click

from hops._format import age, info, section, table, truncate
from hops._runner import kubectl_json, run, run_json
from hops._workload import Workload, resolve_app

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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age_str(timestamp: str | None) -> str:
    """Convert an ISO timestamp to a human-readable age."""
    if not timestamp:
        return "?"
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return age((_now() - dt).total_seconds())
    except (ValueError, TypeError):
        return "?"


def _resolve(app_name: str, namespace: str | None) -> Workload:
    """Resolve app name to a workload or exit with error."""
    wl = resolve_app(app_name, namespace)
    if not wl:
        info(f"error: could not find app {app_name!r}")
        raise SystemExit(1)
    return wl


@click.group()
def cli():
    """Application listing, logs, and diagnostics."""


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

            age_str = _age_str(meta.get("creationTimestamp"))
            rows.append([ns, name, k, ready_str, age_str])

    rows.sort(key=lambda r: (r[0], r[1]))
    table(["NAMESPACE", "NAME", "KIND", "READY", "AGE"], rows)


@cli.command()
@click.argument("app")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (auto-detected if omitted)"
)
def pods(app: str, namespace: str | None):
    """Pods for a specific app with status, restarts, node, age."""
    wl = _resolve(app, namespace)

    data = kubectl_json("pods", namespace=wl.namespace)
    rows = []
    for item in data.get("items", []):
        meta = item.get("metadata", {})
        name = meta.get("name", "")
        # Match pods belonging to the resolved workload
        if not name.startswith(wl.name):
            continue
        spec = item.get("spec", {})
        status = item.get("status", {})
        phase = status.get("phase", "?")
        node = spec.get("nodeName", "?")
        age_str = _age_str(meta.get("creationTimestamp"))

        # Restarts and container status
        restarts = 0
        container_statuses = status.get("containerStatuses", [])
        for cs in container_statuses:
            restarts += cs.get("restartCount", 0)

        # Check for waiting reasons (CrashLoopBackOff, etc.)
        for cs in container_statuses:
            waiting = cs.get("state", {}).get("waiting", {})
            if waiting:
                phase = waiting.get("reason", phase)
                break

        rows.append([name, node, phase, str(restarts), age_str])

    if not rows:
        info(f"No pods found for {wl.name!r} in {wl.namespace}")
        return
    table(["POD", "NODE", "STATUS", "RESTARTS", "AGE"], rows)


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

    # Filter
    if not show_all:
        items = [e for e in items if e.get("type", "Normal") != "Normal"]
    if not namespace:
        items = [
            e
            for e in items
            if e.get("metadata", {}).get("namespace", "") not in _SYSTEM_NS
        ]

    # Take last N
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
        last_seen = _age_str(e.get("lastTimestamp"))
        count = e.get("count", 1)
        count_str = f"x{count}" if count > 1 else ""
        rows.append([last_seen, ns, etype, reason, obj, count_str, msg])

    table(["AGE", "NS", "TYPE", "REASON", "OBJECT", "#", "MESSAGE"], rows)


@cli.command()
@click.argument("app")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (auto-detected if omitted)"
)
@click.option("-c", "--container", default=None, help="Container name (default: all)")
@click.option("--since", default="1h", help="Time window (default: 1h)")
@click.option("--lines", default=50, help="Max lines to show")
@click.option("--previous", is_flag=True, help="Show previous container logs")
def logs(
    app: str,
    namespace: str | None,
    container: str | None,
    since: str,
    lines: int,
    previous: bool,
):
    """Pod logs for an app. Auto-selects the first matching pod.

    Prefer 'hops query logs' for apps with VictoriaLogs/Vector support.
    """
    wl = _resolve(app, namespace)

    # Find matching pods
    data = kubectl_json("pods", namespace=wl.namespace)
    matching = []
    for item in data.get("items", []):
        name = item["metadata"]["name"]
        if name.startswith(wl.name):
            phase = item.get("status", {}).get("phase", "")
            matching.append((name, phase))

    if not matching:
        info(f"No pods found for {wl.name!r} in {wl.namespace}")
        return

    # Prefer Running pods
    pod = next(
        (name for name, phase in matching if phase == "Running"),
        matching[0][0],
    )

    args = [
        "kubectl",
        "logs",
        pod,
        "-n",
        wl.namespace,
        f"--since={since}",
        f"--tail={lines}",
    ]
    if container:
        args.extend(["-c", container])
    else:
        args.append("--all-containers")
    if previous:
        args.append("--previous")

    result = run(args, timeout=30, check=False)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        info(f"error: {stderr}" if stderr else f"error: kubectl logs failed for {pod}")
        return

    output = result.stdout.strip()
    if output:
        info("note: prefer 'hops query logs' for apps with Vector support")
        container_hint = f", container={container}" if container else ""
        info(f"--- {pod} (last {lines} lines, since {since}{container_hint}) ---")
        print(output)
    else:
        info(f"No logs from {pod} in the last {since}")


@cli.command()
@click.argument("app")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (auto-detected if omitted)"
)
def resources(app: str, namespace: str | None):
    """Pod resource usage vs requests/limits for an app."""
    wl = _resolve(app, namespace)

    # Get pod specs for requests/limits
    spec_data = kubectl_json("pods", namespace=wl.namespace)
    pod_specs: dict[str, list[dict]] = {}
    for item in spec_data.get("items", []):
        name = item["metadata"]["name"]
        if name.startswith(wl.name):
            containers = item.get("spec", {}).get("containers", [])
            pod_specs[name] = containers

    if not pod_specs:
        info(f"No pods found for {wl.name!r} in {wl.namespace}")
        return

    # Get current usage from metrics API (kubectl top --containers)
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

            cpu_use = usage.get("cpu", "-")
            cpu_req = req.get("cpu", "-")
            cpu_lim = lim.get("cpu", "-")
            mem_use = usage.get("memory", "-")
            mem_req = req.get("memory", "-")
            mem_lim = lim.get("memory", "-")

            rows.append(
                [
                    pod_name,
                    cname,
                    cpu_use,
                    cpu_req,
                    cpu_lim,
                    mem_use,
                    mem_req,
                    mem_lim,
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
        age_str = _age_str(refresh) if refresh else "?"
        row = [ns, name, sync_status, age_str]
        if message:
            row.append(message)
        rows.append(row)

    rows.sort(key=lambda r: (r[0], r[1]))
    headers = ["NAMESPACE", "NAME", "STATUS", "LAST SYNC"]
    # Add message column if any have errors
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
def diagnose(app: str, namespace: str | None):
    """Composite diagnostic: Flux status, pods, events, logs, restarts.

    Single command replacing 5+ separate kubectl/flux calls.
    """
    wl = _resolve(app, namespace)

    # 1. Flux Kustomization + HelmRelease
    section("FLUX")
    _diagnose_flux(app, wl.namespace)

    # 2. Pods
    section("PODS")
    pod_data = kubectl_json("pods", namespace=wl.namespace)
    pod_rows = []
    restart_details = []
    for item in pod_data.get("items", []):
        meta = item.get("metadata", {})
        name = meta.get("name", "")
        if not name.startswith(wl.name):
            continue
        spec = item.get("spec", {})
        status = item.get("status", {})
        phase = status.get("phase", "?")
        node = spec.get("nodeName", "?")
        age_str = _age_str(meta.get("creationTimestamp"))

        restarts = 0
        for cs in status.get("containerStatuses", []):
            restarts += cs.get("restartCount", 0)
            # Collect restart details
            if cs.get("restartCount", 0) > 0:
                last = cs.get("lastState", {}).get("terminated", {})
                if last:
                    restart_details.append(
                        {
                            "pod": name,
                            "container": cs.get("name", ""),
                            "exit_code": last.get("exitCode", "?"),
                            "reason": last.get("reason", "?"),
                            "finished": _age_str(last.get("finishedAt")),
                        }
                    )

            # Check waiting state
            waiting = cs.get("state", {}).get("waiting", {})
            if waiting:
                phase = waiting.get("reason", phase)

        pod_rows.append([name, node, phase, str(restarts), age_str])

    if pod_rows:
        table(["POD", "NODE", "STATUS", "RESTARTS", "AGE"], pod_rows)
    else:
        info(f"No pods found for {wl.name!r}")

    # Restart details
    if restart_details:
        info("")
        info("Restart details:")
        for rd in restart_details:
            info(
                f"  {rd['pod']}/{rd['container']}: "
                f"exit={rd['exit_code']} reason={rd['reason']} "
                f"({rd['finished']} ago)"
            )

    # 3. Events (non-Normal, filtered to app)
    section(f"EVENTS (non-Normal, {wl.namespace})")
    events_args = [
        "kubectl",
        "get",
        "events",
        "-n",
        wl.namespace,
        "--sort-by=.lastTimestamp",
        "-o",
        "json",
    ]
    events_data = run_json(events_args, timeout=30)
    event_items = events_data.get("items", [])
    # Filter to app-related objects and non-Normal
    app_events = []
    for e in event_items:
        if e.get("type", "Normal") == "Normal":
            continue
        obj = e.get("involvedObject", {})
        obj_name = obj.get("name", "")
        if obj_name.startswith(wl.name):
            app_events.append(e)

    app_events = app_events[-20:]  # Last 20
    if app_events:
        event_rows = []
        for e in app_events:
            reason = e.get("reason", "?")
            obj = e.get("involvedObject", {})
            obj_str = f"{obj.get('kind', '?')}/{obj.get('name', '?')}"
            msg = truncate(e.get("message", ""), 100)
            last_seen = _age_str(e.get("lastTimestamp"))
            event_rows.append([last_seen, reason, obj_str, msg])
        table(["AGE", "REASON", "OBJECT", "MESSAGE"], event_rows)
    else:
        info("(none)")

    # 4. Recent logs (last 20 lines, prefer errors/warnings)
    section("LOGS (recent)")
    matching_pods = [
        item
        for item in pod_data.get("items", [])
        if item["metadata"]["name"].startswith(wl.name)
        and item.get("status", {}).get("phase") == "Running"
    ]
    if matching_pods:
        pod_name = matching_pods[0]["metadata"]["name"]
        result = run(
            [
                "kubectl",
                "logs",
                pod_name,
                "-n",
                wl.namespace,
                "--since=1h",
                "--tail=20",
            ],
            timeout=15,
            check=False,
        )
        output = (result.stdout or "").strip()
        if output:
            print(output)
        else:
            info("(no recent logs)")
    else:
        info("(no running pods)")


def _diagnose_flux(app: str, namespace: str):
    """Show Flux Kustomization and HelmRelease status for an app."""
    # Kustomization (check app namespace first, then flux-system)
    ks_found = False
    for ks_ns in [namespace, "flux-system"]:
        try:
            ks_data = run_json(
                ["kubectl", "get", "kustomization", app, "-n", ks_ns, "-o", "json"],
                timeout=10,
            )
            ks_status = _flux_ready_status(ks_data)
            info(f"Kustomization: {app}  {ks_status}")
            ks_found = True
            break
        except SystemExit:
            continue
    if not ks_found:
        info(f"Kustomization: {app}  (not found)")

    # HelmRelease
    try:
        hr_data = run_json(
            ["kubectl", "get", "helmrelease", app, "-n", namespace, "-o", "json"],
            timeout=10,
        )
        hr_status = _flux_ready_status(hr_data)
        info(f"HelmRelease:   {app}  {hr_status}")
    except SystemExit:
        info(f"HelmRelease:   {app}  (not found)")


def _flux_ready_status(data: dict) -> str:
    """Extract Ready condition from a Flux resource."""
    conditions = data.get("status", {}).get("conditions", [])
    for cond in conditions:
        if cond.get("type") == "Ready":
            status = "Ready" if cond.get("status") == "True" else "Not Ready"
            msg = cond.get("message", "")
            if msg and status == "Not Ready":
                return f"{status}: {truncate(msg, 100)}"
            return status
    return "Unknown"
