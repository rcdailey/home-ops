"""App domain: application listing, debugging, and diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone

import click

from hops._format import age, info, kv, section, table, truncate
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
    """Resolve app name to a workload or exit with error.

    Used by exec-based commands that require a live parent controller
    (ls/cat/du/resources). Commands that operate on pods directly
    should use `_resolve_pods` instead so they survive TTL'd Jobs and
    other orphan-pod cases.
    """
    wl = resolve_app(app_name, namespace)
    if not wl:
        info(f"error: could not find app {app_name!r}")
        raise SystemExit(1)
    return wl


def _resolve_pods(name: str, namespace: str | None) -> tuple[str, list[dict]]:
    """Resolve a name to pods, newest-first, across workload and orphan cases.

    Strategy (in order):
    1. Try workload resolution. If it matches, return its pods.
    2. Fall back to pod-name lookup: exact match or name prefix.
       Handles pods whose parent workload has been deleted (Job TTL,
       manual workload removal, etc.) but whose pod objects still exist.

    Returns (effective_namespace, pods). Exits with a single-line error
    if nothing matches.
    """
    wl = resolve_app(name, namespace)
    if wl:
        data = kubectl_json("pods", namespace=wl.namespace)
        pods = [
            p
            for p in data.get("items", [])
            if p["metadata"]["name"].startswith(wl.name)
        ]
        pods.sort(
            key=lambda p: p["metadata"].get("creationTimestamp", ""),
            reverse=True,
        )
        if pods:
            return wl.namespace, pods
        # Workload exists but has no pods yet (rare; treat as error below).

    data = kubectl_json("pods", namespace=namespace)
    orphans = [
        p
        for p in data.get("items", [])
        if p["metadata"]["name"] == name or p["metadata"]["name"].startswith(f"{name}-")
    ]
    if not orphans:
        scope = f" in {namespace}" if namespace else ""
        info(f"error: no workload or pod matching {name!r}{scope}")
        raise SystemExit(1)

    orphans.sort(
        key=lambda p: p["metadata"].get("creationTimestamp", ""),
        reverse=True,
    )
    effective_ns = orphans[0]["metadata"]["namespace"]
    return effective_ns, orphans


def _pick_pod_for_logs(pods: list[dict]) -> dict:
    """Pick the best pod for reading logs from a candidate list.

    Prefers Running (live logs), then Succeeded, then Failed, then any.
    Input list must be newest-first; stable sort preserves that within a
    phase tier.
    """
    phase_priority = {"Running": 0, "Succeeded": 1, "Failed": 2}
    return sorted(
        pods,
        key=lambda p: phase_priority.get(p.get("status", {}).get("phase", ""), 3),
    )[0]


def _find_running_pod(wl: Workload) -> str:
    """Find a Running pod for a workload (for exec). Exits if none."""
    data = kubectl_json("pods", namespace=wl.namespace)
    for p in data.get("items", []):
        if p["metadata"]["name"].startswith(wl.name) and (
            p.get("status", {}).get("phase") == "Running"
        ):
            return p["metadata"]["name"]
    info(f"error: no running pods for {wl.name!r} in {wl.namespace}")
    raise SystemExit(1)


def _exec_stderr(stderr: str) -> str:
    """Clean kubectl exec stderr by removing informational lines."""
    lines = [
        ln
        for ln in stderr.strip().splitlines()
        if not ln.startswith("Defaulted container")
    ]
    return "\n".join(lines).strip()


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
    ns, pods_list = _resolve_pods(app, namespace)
    chosen = _pick_pod_for_logs(pods_list)
    pod = chosen["metadata"]["name"]
    phase = chosen.get("status", {}).get("phase", "?")
    terminated = phase in ("Succeeded", "Failed")

    args = [
        "kubectl",
        "logs",
        pod,
        "-n",
        ns,
        f"--tail={lines}",
    ]
    # --since is meaningless for --previous or terminated pods (bounded by container lifetime).
    if not previous and not terminated:
        args.append(f"--since={since}")
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
        scope = "since boot" if terminated else f"since {since}"
        info(f"--- {pod} [{phase}] (last {lines} lines, {scope}{container_hint}) ---")
        print(output)
    else:
        window = "in this container" if terminated else f"in the last {since}"
        info(f"No logs from {pod} [{phase}] {window}")


@cli.command("pod")
@click.argument("app")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (auto-detected if omitted)"
)
@click.option(
    "--name",
    "pod_name",
    default=None,
    help="Specific pod name (default: most recent)",
)
@click.option(
    "--events/--no-events", default=True, help="Include event timeline (default: on)"
)
def pod_detail(app: str, namespace: str | None, pod_name: str | None, events: bool):
    """Detailed pod state: phase, container timings, event timeline.

    Replaces 'kubectl describe pod' for diagnosing per-pod lifecycle issues
    (startup races, image pull delays, crash-then-succeed patterns). Shows
    both Normal and Warning events sorted by lastTimestamp.
    """
    ns, pods = _resolve_pods(app, namespace)
    if pod_name:
        pods = [p for p in pods if p["metadata"]["name"] == pod_name]
    if not pods:
        target = pod_name or app
        info(f"error: no pods matching {target!r} in {ns}")
        raise SystemExit(1)
    pod = pods[0]
    meta = pod["metadata"]
    spec = pod.get("spec", {})
    status = pod.get("status", {})
    name = meta["name"]

    # Summary
    section("POD")
    kv(
        [
            ("name", name),
            ("namespace", ns),
            ("node", spec.get("nodeName", "?")),
            ("phase", status.get("phase", "?")),
            ("age", _age_str(meta.get("creationTimestamp"))),
        ]
    )

    # Containers (init + regular). Each container has a state (running/waiting/terminated)
    # plus lastState for prior runs. We surface whichever is informative.
    init_statuses = status.get("initContainerStatuses", [])
    container_statuses = status.get("containerStatuses", [])
    all_statuses = [("init", cs) for cs in init_statuses] + [
        ("app", cs) for cs in container_statuses
    ]
    if all_statuses:
        section("CONTAINERS")
        rows = []
        for kind, cs in all_statuses:
            cname = cs.get("name", "?")
            restarts = cs.get("restartCount", 0)
            state = cs.get("state", {})
            state_str, detail = _format_container_state(state)
            rows.append([kind, cname, str(restarts), state_str, detail])
        table(["KIND", "CONTAINER", "RESTARTS", "STATE", "DETAIL"], rows)

        # Previous termination details (for containers that restarted).
        # Auto-fetch --previous logs for each so the caller sees crash output
        # inline, not after a second command.
        restarted = [
            cs for _, cs in all_statuses if cs.get("lastState", {}).get("terminated")
        ]
        if restarted:
            info("")
            info("Previous terminations:")
            table(
                ["CONTAINER", "EXIT", "REASON", "FINISHED"],
                [
                    [
                        cs.get("name", "?"),
                        str(cs["lastState"]["terminated"].get("exitCode", "?")),
                        cs["lastState"]["terminated"].get("reason", "?"),
                        _age_str(cs["lastState"]["terminated"].get("finishedAt")),
                    ]
                    for cs in restarted
                ],
            )
            section("PREVIOUS LOGS")
            for cs in restarted:
                cname = cs.get("name", "?")
                prev = run(
                    [
                        "kubectl",
                        "logs",
                        name,
                        "-n",
                        ns,
                        "-c",
                        cname,
                        "--previous",
                        "--tail=30",
                    ],
                    timeout=15,
                    check=False,
                )
                out = (prev.stdout or "").strip()
                info(f"--- {cname} (previous, last 30 lines) ---")
                print(out if out else "(none available)")

    # Events scoped to this specific pod
    if events:
        section("EVENTS (pod-scoped)")
        ev_data = run_json(
            [
                "kubectl",
                "get",
                "events",
                "-n",
                ns,
                "--field-selector",
                f"involvedObject.name={name}",
                "--sort-by=.lastTimestamp",
                "-o",
                "json",
            ],
            timeout=15,
        )
        items = ev_data.get("items", [])
        if not items:
            info("(none)")
        else:
            rows = []
            for e in items:
                rows.append(
                    [
                        _age_str(e.get("lastTimestamp") or e.get("eventTime")),
                        e.get("type", "?"),
                        e.get("reason", "?"),
                        f"x{e.get('count', 1)}" if e.get("count", 1) > 1 else "",
                        truncate(e.get("message", ""), 100),
                    ]
                )
            table(["AGE", "TYPE", "REASON", "#", "MESSAGE"], rows)


def _format_container_state(state: dict) -> tuple[str, str]:
    """Summarize a containerStatus.state dict as (label, detail)."""
    if "running" in state:
        started = state["running"].get("startedAt")
        return "Running", f"started {_age_str(started)} ago" if started else ""
    if "terminated" in state:
        t = state["terminated"]
        parts = [f"exit={t.get('exitCode', '?')}"]
        if t.get("reason"):
            parts.append(t["reason"])
        if t.get("finishedAt"):
            parts.append(f"finished {_age_str(t['finishedAt'])} ago")
        return "Terminated", " ".join(parts)
    if "waiting" in state:
        w = state["waiting"]
        reason = w.get("reason", "Waiting")
        msg = w.get("message", "")
        return reason, truncate(msg, 80) if msg else ""
    return "?", ""


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

    Works for both workload apps (Deployments, etc.) and gateway-only apps
    (external services proxied via Backend/Service + HTTPRoute).
    """
    wl = resolve_app(app, namespace)

    # Determine effective namespace: from workload, or from gateway resource lookup
    ns = wl.namespace if wl else _find_gateway_namespace(app, namespace)
    if not ns:
        info(f"error: could not find app {app!r}")
        raise SystemExit(1)

    # 1. Flux Kustomization + HelmRelease
    section("FLUX")
    _diagnose_flux(app, ns)

    if wl:
        _diagnose_workload(wl, ns)
    else:
        _diagnose_gateway(app, ns)

    # Events (non-Normal, filtered to app)
    _diagnose_events(app, ns)


@cli.command("ls")
@click.argument("app")
@click.argument("path")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (auto-detected if omitted)"
)
@click.option("-c", "--container", default=None, help="Container name")
def ls_path(app: str, path: str, namespace: str | None, container: str | None):
    """List files at a path inside an app container."""
    wl = _resolve(app, namespace)
    pod = _find_running_pod(wl)
    args = ["kubectl", "exec", pod, "-n", wl.namespace]
    if container:
        args.extend(["-c", container])
    args.extend(["--", "ls", "-la", path])
    result = run(args, timeout=15, check=False)
    if result.returncode != 0:
        stderr = _exec_stderr(result.stderr or "")
        info(f"error: {stderr}" if stderr else f"error: ls failed in {pod}")
        raise SystemExit(1)
    output = (result.stdout or "").strip()
    if output:
        print(output)


@cli.command("cat")
@click.argument("app")
@click.argument("path")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (auto-detected if omitted)"
)
@click.option("-c", "--container", default=None, help="Container name")
@click.option("--lines", default=200, help="Max lines to show (default: 200)")
def cat_file(
    app: str, path: str, namespace: str | None, container: str | None, lines: int
):
    """Read a file from inside an app container."""
    wl = _resolve(app, namespace)
    pod = _find_running_pod(wl)
    args = ["kubectl", "exec", pod, "-n", wl.namespace]
    if container:
        args.extend(["-c", container])
    args.extend(["--", "head", "-n", str(lines), path])
    result = run(args, timeout=15, check=False)
    if result.returncode != 0:
        stderr = _exec_stderr(result.stderr or "")
        info(f"error: {stderr}" if stderr else f"error: cat failed in {pod}")
        raise SystemExit(1)
    output = (result.stdout or "").strip()
    if output:
        print(output)


@cli.command("du")
@click.argument("app")
@click.argument("path")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (auto-detected if omitted)"
)
@click.option("-c", "--container", default=None, help="Container name")
@click.option("-d", "--depth", default=1, help="Directory depth (default: 1)", type=int)
def du_path(
    app: str, path: str, namespace: str | None, container: str | None, depth: int
):
    """Disk usage at a path inside an app container."""
    wl = _resolve(app, namespace)
    pod = _find_running_pod(wl)
    args = ["kubectl", "exec", pod, "-n", wl.namespace]
    if container:
        args.extend(["-c", container])
    args.extend(["--", "du", "-h", f"-d{depth}", path])
    result = run(args, timeout=30, check=False)
    if result.returncode != 0:
        stderr = _exec_stderr(result.stderr or "")
        info(f"error: {stderr}" if stderr else f"error: du failed in {pod}")
        raise SystemExit(1)
    output = (result.stdout or "").strip()
    if output:
        print(output)


def _find_gateway_namespace(app: str, namespace: str | None) -> str | None:
    """Find the namespace of a gateway-only app (Backend or Service + HTTPRoute)."""
    for resource in ("backends.gateway.envoyproxy.io", "services"):
        try:
            args = ["kubectl", "get", resource, app, "-o", "json"]
            if namespace:
                args.extend(["-n", namespace])
            else:
                args.append("--all-namespaces")
            data = run_json(args, timeout=10, quiet=True)
            # Single resource response
            ns = data.get("metadata", {}).get("namespace")
            if ns:
                return ns
        except SystemExit:
            continue
    return None


def _diagnose_workload(wl: Workload, ns: str):
    """Diagnose a workload-based app: pods, restarts, logs."""
    section("PODS")
    pod_data = kubectl_json("pods", namespace=ns)
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

            waiting = cs.get("state", {}).get("waiting", {})
            if waiting:
                phase = waiting.get("reason", phase)

        pod_rows.append([name, node, phase, str(restarts), age_str])

    if pod_rows:
        table(["POD", "NODE", "STATUS", "RESTARTS", "AGE"], pod_rows)
    else:
        info(f"No pods found for {wl.name!r}")

    if restart_details:
        info("")
        info("Restart details:")
        for rd in restart_details:
            info(
                f"  {rd['pod']}/{rd['container']}: "
                f"exit={rd['exit_code']} reason={rd['reason']} "
                f"({rd['finished']} ago)"
            )

    # Recent logs
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
                ns,
                "--all-containers",
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

    # Previous crash logs (auto-shown when restarts detected)
    if restart_details and matching_pods:
        section("LOGS (previous crash)")
        pod_name = matching_pods[0]["metadata"]["name"]
        # Show previous logs for each container that restarted
        shown = False
        for rd in restart_details:
            container_name = rd["container"]
            result = run(
                [
                    "kubectl",
                    "logs",
                    pod_name,
                    "-n",
                    ns,
                    "-c",
                    container_name,
                    "--previous",
                    "--tail=30",
                ],
                timeout=15,
                check=False,
            )
            output = (result.stdout or "").strip()
            if output:
                info(f"--- {container_name} (previous, last 30 lines) ---")
                print(output)
                shown = True
        if not shown:
            info("(no previous logs available)")


def _diagnose_gateway(app: str, ns: str):
    """Diagnose a gateway-only app: Backend/Service + HTTPRoute status."""
    # Backend (Envoy Gateway)
    section("BACKEND")
    backend_found = False
    try:
        data = run_json(
            [
                "kubectl",
                "get",
                "backends.gateway.envoyproxy.io",
                app,
                "-n",
                ns,
                "-o",
                "json",
            ],
            timeout=10,
            quiet=True,
        )
        backend_found = True
        spec = data.get("spec", {})
        endpoints = spec.get("endpoints", [])
        tls = spec.get("tls", {})
        endpoint_strs = []
        for ep in endpoints:
            ip_spec = ep.get("ip", {})
            fqdn_spec = ep.get("fqdn", {})
            if ip_spec:
                endpoint_strs.append(
                    f"{ip_spec.get('address', '?')}:{ip_spec.get('port', '?')}"
                )
            elif fqdn_spec:
                endpoint_strs.append(
                    f"{fqdn_spec.get('hostname', '?')}:{fqdn_spec.get('port', '?')}"
                )
        info(f"Backend: {app}")
        info(f"  endpoints: {', '.join(endpoint_strs) if endpoint_strs else '(none)'}")
        if tls:
            skip = tls.get("insecureSkipVerify", False)
            info(f"  tls: insecureSkipVerify={skip}")
        _print_conditions(data)
    except SystemExit:
        pass

    # Service + Endpoints (headless external service pattern)
    if not backend_found:
        try:
            svc_data = run_json(
                ["kubectl", "get", "service", app, "-n", ns, "-o", "json"],
                timeout=10,
                quiet=True,
            )
            ports = svc_data.get("spec", {}).get("ports", [])
            port_strs = [f"{p.get('name', '?')}:{p.get('port', '?')}" for p in ports]
            info(f"Service: {app}")
            info(f"  ports: {', '.join(port_strs)}")

            # Check endpoints
            try:
                ep_data = run_json(
                    ["kubectl", "get", "endpoints", app, "-n", ns, "-o", "json"],
                    timeout=10,
                    quiet=True,
                )
                subsets = ep_data.get("subsets", [])
                addrs = []
                for s in subsets:
                    for a in s.get("addresses", []):
                        ep_ports = [str(p.get("port", "?")) for p in s.get("ports", [])]
                        addrs.append(f"{a.get('ip', '?')}:{','.join(ep_ports)}")
                info(f"  endpoints: {', '.join(addrs) if addrs else '(none)'}")
            except SystemExit:
                info("  endpoints: (not found)")
        except SystemExit:
            info(f"No Backend or Service found for {app!r}")

    # HTTPRoute
    section("HTTPROUTE")
    try:
        route_data = run_json(
            ["kubectl", "get", "httproute", app, "-n", ns, "-o", "json"],
            timeout=10,
            quiet=True,
        )
        spec = route_data.get("spec", {})
        hostnames = spec.get("hostnames", [])
        info(f"HTTPRoute: {app}")
        info(f"  hostnames: {', '.join(hostnames) if hostnames else '(none)'}")

        # Show backend refs
        for i, rule in enumerate(spec.get("rules", [])):
            refs = rule.get("backendRefs", [])
            for ref in refs:
                kind = ref.get("kind", "Service")
                name = ref.get("name", "?")
                port = ref.get("port", "?")
                info(f"  backendRef: {kind}/{name}:{port}")

        # Parent status (accepted/resolved conditions from gateway)
        parents = route_data.get("status", {}).get("parents", [])
        for parent in parents:
            gw = parent.get("parentRef", {}).get("name", "?")
            info(f"  gateway: {gw}")
            for cond in parent.get("conditions", []):
                ctype = cond.get("type", "?")
                cstatus = cond.get("status", "?")
                reason = cond.get("reason", "")
                msg = cond.get("message", "")
                status_str = "yes" if cstatus == "True" else "no"
                detail = f" ({reason}: {truncate(msg, 80)})" if msg else ""
                info(f"    {ctype}: {status_str}{detail}")
    except SystemExit:
        info(f"HTTPRoute {app!r} not found in {ns}")


def _print_conditions(data: dict):
    """Print status conditions from a resource, if any."""
    conditions = data.get("status", {}).get("conditions", [])
    if not conditions:
        return
    for cond in conditions:
        ctype = cond.get("type", "?")
        cstatus = cond.get("status", "?")
        msg = cond.get("message", "")
        status_str = "yes" if cstatus == "True" else "no"
        detail = f": {truncate(msg, 80)}" if msg else ""
        info(f"  {ctype}: {status_str}{detail}")


def _diagnose_events(app: str, ns: str):
    """Show non-Normal events filtered to an app name."""
    section(f"EVENTS (non-Normal, {ns})")
    events_args = [
        "kubectl",
        "get",
        "events",
        "-n",
        ns,
        "--sort-by=.lastTimestamp",
        "-o",
        "json",
    ]
    events_data = run_json(events_args, timeout=30)
    event_items = events_data.get("items", [])
    app_events = []
    for e in event_items:
        if e.get("type", "Normal") == "Normal":
            continue
        obj = e.get("involvedObject", {})
        obj_name = obj.get("name", "")
        if obj_name.startswith(app):
            app_events.append(e)

    # Deduplicate events with identical messages, keeping the most recent.
    # Strip trailing "Last Helm logs:" blocks before comparing (timestamps vary).
    def _dedup_key(msg: str) -> str:
        idx = msg.find("\n\nLast Helm logs:")
        return msg[:idx] if idx != -1 else msg

    seen_keys: dict[str, int] = {}
    deduped: list[dict] = []
    for e in reversed(app_events):
        key = _dedup_key(e.get("message", ""))
        if key not in seen_keys:
            seen_keys[key] = 0
            deduped.append(e)
        seen_keys[key] += 1
    deduped.reverse()
    deduped = deduped[-20:]

    if deduped:
        event_rows = []
        for e in deduped:
            reason = e.get("reason", "?")
            obj = e.get("involvedObject", {})
            obj_str = f"{obj.get('kind', '?')}/{obj.get('name', '?')}"
            msg = _compact_event_message(e.get("message", ""))
            last_seen = _age_str(e.get("lastTimestamp"))
            count = seen_keys.get(_dedup_key(e.get("message", "")), 1)
            count_str = f"x{count}" if count > 1 else ""
            event_rows.append([last_seen, reason, obj_str, count_str, msg])
        table(["AGE", "REASON", "OBJECT", "#", "MESSAGE"], event_rows)
    else:
        info("(none)")


def _compact_event_message(msg: str) -> str:
    """Shorten verbose Helm template error chains to the actionable tail."""
    # Helm template errors have a deeply nested "error calling include:" chain
    # where only the final segment is actionable.
    if "error calling include:" in msg or "error calling tpl:" in msg:
        # Find the last colon-separated clause which has the real error
        for marker in ("error calling tpl:", "error calling include:"):
            idx = msg.rfind(marker)
            if idx != -1:
                tail = msg[idx:].strip()
                # Prefix so context isn't lost
                prefix = msg[:80].split(":")[0] if len(msg) > 200 else ""
                if prefix:
                    return f"{prefix}: ... {tail}"
                return tail
    return msg


def _diagnose_flux(app: str, namespace: str):
    """Show Flux Kustomization and HelmRelease status for an app."""
    # Kustomization (check app namespace first, then flux-system)
    ks_found = False
    for ks_ns in [namespace, "flux-system"]:
        try:
            ks_data = run_json(
                ["kubectl", "get", "kustomization", app, "-n", ks_ns, "-o", "json"],
                timeout=10,
                quiet=True,
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
            quiet=True,
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
                return f"{status}: {_compact_event_message(msg)}"
            return status
    return "Unknown"
