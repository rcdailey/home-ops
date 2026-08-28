"""App-specific Click commands for logs and diagnostics."""

from __future__ import annotations

from typing import Never

import click

from hops.app import cli
from hops.app.events import diagnose_events as _diagnose_events
from hops.app.gather import (
    diagnose_externalsecrets as _diagnose_externalsecrets,
)
from hops.app.gather import (
    diagnose_flux as _diagnose_flux,
)
from hops.app.gather import (
    diagnose_gateway as _diagnose_gateway,
)
from hops.app.gather import (
    diagnose_network_policies as _diagnose_network_policies,
)
from hops.app.gather import (
    diagnose_services as _diagnose_services,
)
from hops.app.gather import (
    diagnose_workload as _diagnose_workload,
)
from hops.app.log_history import previous_container_logs
from hops.app.pod_detail import diagnose_pod as _diagnose_pod
from hops.core.format import info, section
from hops.core.resolve import TargetKind, resolve
from hops.core.runner import run
from hops.core.workload import resolve_pods, select_pods_for_logs, suggest_near_matches


def _not_found(name: str, namespace: str | None) -> Never:
    """Print error with near-match suggestions and exit."""
    hints = suggest_near_matches(name, namespace)
    info(f"error: could not find app {name!r}")
    if hints:
        info(f"  similar: {', '.join(hints)}")
    raise SystemExit(1)


@cli.command()
@click.argument("app")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (auto-detected if omitted)"
)
@click.option("-c", "--container", default=None, help="Container name (default: all)")
@click.option("--since", default="1h", help="Time window (default: 1h)")
@click.option(
    "--lines",
    default=50,
    type=click.IntRange(min=1),
    help="Max lines across all replicas",
)
@click.option("--previous", is_flag=True, help="Show previous container logs")
@click.option(
    "-g",
    "--grep",
    default=None,
    help="Filter log lines by regex pattern (searches all logs, not just tail)",
)
@click.option(
    "-A",
    "--after-context",
    default=0,
    type=int,
    help="Lines of context after each grep match",
)
def logs(
    app: str,
    namespace: str | None,
    container: str | None,
    since: str,
    lines: int,
    previous: bool,
    grep: str | None,
    after_context: int,
):
    """Pod logs for every running replica of an app.

    With --grep, fetches all logs in the time window and filters by
    regex pattern (removes --tail limit so matches are not missed).

    Prefer 'hops query logs' for apps collected by OpenTelemetry.
    """
    result = resolve_pods(app, namespace)
    if not result:
        _not_found(app, namespace)
    ns, pods_list = result
    chosen_pods = select_pods_for_logs(pods_list)
    per_pod_lines = max(1, lines // len(chosen_pods))

    if previous and not container:
        found = False
        for chosen in chosen_pods:
            output = previous_container_logs(chosen, ns, per_pod_lines)
            if output is None:
                continue
            found = True
            if grep:
                output = _grep_logs(output, grep, after_context, per_pod_lines)
            click.echo(output)
        if not found:
            info("No previous container instances found.")
        return

    if previous and container:
        chosen_pods = [
            pod for pod in chosen_pods if _has_previous_instance(pod, container)
        ]
        if not chosen_pods:
            info(f"No previous instances found for container {container!r}.")
            return

    shown = 0
    for chosen in chosen_pods:
        shown += _show_pod_logs(
            chosen,
            ns,
            container,
            since,
            per_pod_lines,
            previous,
            grep,
            after_context,
        )
    if not shown:
        extra = f" matching {grep!r}" if grep else ""
        info(f"No logs from {len(chosen_pods)} pods in the last {since}{extra}.")


def _has_previous_instance(pod: dict, container: str) -> bool:
    """Return whether a named container has a terminated previous instance."""
    status = pod.get("status", {})
    containers = [
        *status.get("containerStatuses", []),
        *status.get("initContainerStatuses", []),
    ]
    return any(
        item.get("name") == container and item.get("lastState", {}).get("terminated")
        for item in containers
    )


def _show_pod_logs(
    chosen: dict,
    namespace: str,
    container: str | None,
    since: str,
    lines: int,
    previous: bool,
    grep: str | None,
    after_context: int,
) -> int:
    """Fetch and display logs for one resolved pod."""
    pod = chosen["metadata"]["name"]
    phase = chosen.get("status", {}).get("phase", "?")
    terminated = phase in ("Succeeded", "Failed")
    args = ["kubectl", "logs", pod, "-n", namespace]
    if not grep:
        args.append(f"--tail={lines}")
    if not previous and not terminated:
        args.append(f"--since={since}")
    args.extend(["-c", container] if container else ["--all-containers"])
    if previous:
        args.append("--previous")

    result = run(args, timeout=30, check=False)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        info(f"error: {stderr}" if stderr else f"error: kubectl logs failed for {pod}")
        return 0

    output = result.stdout.strip()
    if grep:
        output = _grep_logs(output, grep, after_context, lines)
    if not output:
        return 0

    container_hint = f", container={container}" if container else ""
    scope = "since boot" if terminated else f"since {since}"
    grep_hint = f", grep={grep!r}" if grep else ""
    info(f"--- {pod} [{phase}] ({scope}{container_hint}{grep_hint}) ---")
    click.echo(output)
    return 1


def _grep_logs(output: str, pattern: str, after_context: int, max_lines: int) -> str:
    """Filter log output by regex pattern with optional context lines."""
    import re

    try:
        regex = re.compile(pattern)
    except re.error as e:
        info(f"error: invalid grep pattern: {e}")
        raise SystemExit(1)

    log_lines = output.splitlines()
    matched: list[str] = []
    remaining_context = 0

    for line in log_lines:
        if regex.search(line):
            # Insert separator when matches are non-contiguous
            if matched and remaining_context == 0:
                matched.append("--")
            matched.append(line)
            remaining_context = after_context
        elif remaining_context > 0:
            matched.append(line)
            remaining_context -= 1

    # Cap output to --lines
    if len(matched) > max_lines:
        matched = matched[-max_lines:]

    return "\n".join(matched)


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

    is_batch_workload = target.workload and target.workload.kind in {"cronjobs", "jobs"}

    if target.kind == TargetKind.POD or is_batch_workload:
        _diagnose_workload(target.name, target.namespace)
        _diagnose_events(target.name, target.namespace)
        return

    section("FLUX")
    _diagnose_flux(app, target.namespace)
    _diagnose_externalsecrets(app, target.namespace)

    if target.kind == TargetKind.WORKLOAD:
        _diagnose_services(app, target.namespace)
        _diagnose_network_policies(app, target.namespace)
        _diagnose_workload(app, target.namespace)
    else:
        _diagnose_gateway(app, target.namespace)

    _diagnose_events(app, target.namespace)
