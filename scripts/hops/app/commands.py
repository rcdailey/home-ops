"""App-specific Click commands: pods, logs, resources, diagnose, exec (ls/cat/du)."""

from __future__ import annotations

import click

from hops.app import cli
from hops.app.gather import (
    diagnose_events as _diagnose_events,
    diagnose_flux as _diagnose_flux,
    diagnose_gateway as _diagnose_gateway,
    diagnose_workload as _diagnose_workload,
)
from hops.app.pod_detail import diagnose_pod as _diagnose_pod
from hops.core.format import age_str, info, section, table
from hops.core.resolve import TargetKind, resolve
from hops.core.runner import kubectl_json, run
from hops.core.workload import (
    Workload,
    find_running_pod,
    pick_pod_for_logs,
    resolve_pods,
    suggest_near_matches,
)


def _resolve(app_name: str, namespace: str | None) -> Workload:
    """Resolve app name to a workload or exit with error.

    Used by exec-based commands that require a live parent controller
    (ls/cat/du/resources). Commands that operate on pods directly
    should use `resolve_pods` instead so they survive TTL'd Jobs and
    other orphan-pod cases.
    """
    from hops.core.workload import resolve_app

    wl = resolve_app(app_name, namespace)
    if not wl:
        _not_found(app_name, namespace)
    return wl


def _not_found(name: str, namespace: str | None) -> None:
    """Print error with near-match suggestions and exit."""
    hints = suggest_near_matches(name, namespace)
    info(f"error: could not find app {name!r}")
    if hints:
        info(f"  similar: {', '.join(hints)}")
    raise SystemExit(1)


def _find_running_pod(wl: Workload) -> str:
    """Find a Running pod for a workload (for exec). Exits if none."""
    pod = find_running_pod(wl)
    if not pod:
        info(f"error: no running pods for {wl.name!r} in {wl.namespace}")
        raise SystemExit(1)
    return pod


def _exec_in_pod(
    app: str,
    namespace: str | None,
    container: str | None,
    command: list[str],
    timeout: int = 15,
) -> None:
    """Resolve app, find a running pod, exec command, print output."""
    wl = _resolve(app, namespace)
    pod = _find_running_pod(wl)
    args = ["kubectl", "exec", pod, "-n", wl.namespace]
    if container:
        args.extend(["-c", container])
    args.extend(["--"] + command)
    result = run(args, timeout=timeout, check=False)
    if result.returncode != 0:
        stderr = result.stderr or ""
        # Strip informational "Defaulted container" lines
        cleaned = "\n".join(
            ln
            for ln in stderr.strip().splitlines()
            if not ln.startswith("Defaulted container")
        ).strip()
        info(f"error: {cleaned}" if cleaned else f"error: exec failed in {pod}")
        raise SystemExit(1)
    output = (result.stdout or "").strip()
    if output:
        print(output)


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
        if not name.startswith(wl.name):
            continue
        spec = item.get("spec", {})
        status = item.get("status", {})
        phase = status.get("phase", "?")
        node = spec.get("nodeName", "?")
        age_val = age_str(meta.get("creationTimestamp"))

        restarts = 0
        container_statuses = status.get("containerStatuses", [])
        for cs in container_statuses:
            restarts += cs.get("restartCount", 0)

        for cs in container_statuses:
            waiting = cs.get("state", {}).get("waiting", {})
            if waiting:
                phase = waiting.get("reason", phase)
                break

        rows.append([name, node, phase, str(restarts), age_val])

    if not rows:
        info(f"No pods found for {wl.name!r} in {wl.namespace}")
        return
    table(["POD", "NODE", "STATUS", "RESTARTS", "AGE"], rows)


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
    result = resolve_pods(app, namespace)
    if not result:
        _not_found(app, namespace)
    ns, pods_list = result
    chosen = pick_pod_for_logs(pods_list)
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
    # --since is meaningless for --previous or terminated pods
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
    _diagnose_pod(app, namespace, pod_name, events)


@cli.command()
@click.argument("app")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (auto-detected if omitted)"
)
@click.option("--explain", is_flag=True, help="Show resolver trace")
def diagnose(app: str, namespace: str | None, explain: bool):
    """Composite diagnostic: Flux status, pods, events, logs, restarts.

    Works for workload apps (Deployments, etc.), gateway-only apps
    (external services proxied via Backend/Service + HTTPRoute), and
    operator-managed pods (CNPG Clusters, etc.) without parent workloads.
    """
    target = resolve(app, namespace, explain=explain)

    if explain and target.explain:
        section("RESOLVER")
        for step in target.explain:
            info(f"  {step}")

    section("FLUX")
    _diagnose_flux(app, target.namespace)

    if target.kind in (TargetKind.WORKLOAD, TargetKind.POD):
        _diagnose_workload(target.name, target.namespace)
    else:
        _diagnose_gateway(app, target.namespace)

    _diagnose_events(app, target.namespace)


@cli.command("ls")
@click.argument("app")
@click.argument("path")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (auto-detected if omitted)"
)
@click.option("-c", "--container", default=None, help="Container name")
def ls_path(app: str, path: str, namespace: str | None, container: str | None):
    """List files at a path inside an app container."""
    _exec_in_pod(app, namespace, container, ["ls", "-la", path])


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
    _exec_in_pod(app, namespace, container, ["head", "-n", str(lines), path])


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
    _exec_in_pod(
        app, namespace, container, ["du", "-h", f"-d{depth}", path], timeout=30
    )
