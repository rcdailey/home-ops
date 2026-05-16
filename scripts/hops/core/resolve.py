"""Unified target resolution for hops commands.

Resolves user-provided names to cluster targets using a registry of
resolvers, each handling a specific resource category. Callers get a
uniform ResolvedTarget instead of branching on resource type.

Resolution order:
1. Workload (Deployment, StatefulSet, DaemonSet, CronJob, Job)
2. Gateway (Backend or Service + HTTPRoute, no pods)
3. Pod (operator-managed pods like CNPG, orphan pods from TTL'd Jobs)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Protocol

import click

from hops.core.runner import run_json
from hops.core.workload import Workload, resolve_app, resolve_pods, suggest_near_matches


class TargetKind:
    """Enumeration of resolved target kinds."""

    WORKLOAD = "workload"
    GATEWAY = "gateway"
    POD = "pod"


@dataclass
class ResolvedTarget:
    """Uniform result from target resolution."""

    kind: str  # TargetKind value
    name: str  # The matched name
    namespace: str
    workload: Workload | None = None  # Set when kind == WORKLOAD
    pods: list[dict] = field(default_factory=list)  # Set when kind in (WORKLOAD, POD)
    explain: list[str] = field(default_factory=list)  # Resolution trace for --explain


class Resolver(Protocol):
    """Protocol for pluggable resolvers."""

    def try_resolve(
        self, name: str, namespace: str | None, explain: bool = False
    ) -> ResolvedTarget | None: ...


class WorkloadResolver:
    """Resolves names to workloads (Deployment, StatefulSet, DaemonSet, etc.)."""

    def try_resolve(
        self, name: str, namespace: str | None, explain: bool = False
    ) -> ResolvedTarget | None:
        wl = resolve_app(name, namespace)
        if not wl:
            return None

        from hops.core.runner import kubectl_json

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

        trace = (
            [f"matched workload {wl.kind}/{wl.name} in {wl.namespace}"]
            if explain
            else []
        )
        return ResolvedTarget(
            kind=TargetKind.WORKLOAD,
            name=wl.name,
            namespace=wl.namespace,
            workload=wl,
            pods=pods,
            explain=trace,
        )


class GatewayResolver:
    """Resolves names to gateway-only apps (Backend or Service + HTTPRoute).

    Handles external services proxied via EnvoyGateway Backend resources
    or headless Kubernetes Services with HTTPRoutes. These have no pods.
    """

    def try_resolve(
        self, name: str, namespace: str | None, explain: bool = False
    ) -> ResolvedTarget | None:
        ns = _find_gateway_namespace(name, namespace)
        if not ns:
            return None
        trace = [f"matched gateway resource {name!r} in {ns}"] if explain else []
        return ResolvedTarget(
            kind=TargetKind.GATEWAY,
            name=name,
            namespace=ns,
            explain=trace,
        )


class PodResolver:
    """Resolves names to pods directly (operator-managed or orphan pods)."""

    def try_resolve(
        self, name: str, namespace: str | None, explain: bool = False
    ) -> ResolvedTarget | None:
        result = resolve_pods(name, namespace)
        if not result:
            return None
        ns, pods = result
        trace = (
            [f"matched {len(pods)} pod(s) in {ns} (no parent workload)"]
            if explain
            else []
        )
        return ResolvedTarget(
            kind=TargetKind.POD,
            name=name,
            namespace=ns,
            pods=pods,
            explain=trace,
        )


_REGISTRY: list[Resolver] = [
    WorkloadResolver(),
    GatewayResolver(),
    PodResolver(),
]


def resolve(
    name: str,
    namespace: str | None = None,
    *,
    explain: bool = False,
) -> ResolvedTarget:
    """Resolve a name to a cluster target.

    Tries resolvers in priority order. Raises SystemExit with
    near-match suggestions if nothing matches.
    """
    trace: list[str] = []
    for resolver in _REGISTRY:
        resolver_name = type(resolver).__name__
        target = resolver.try_resolve(name, namespace, explain=explain)
        if target is not None:
            if explain:
                trace.extend(target.explain)
                target.explain = trace
            return target
        if explain:
            trace.append(f"{resolver_name}: no match")

    hints = suggest_near_matches(name, namespace)
    if explain:
        for step in trace:
            click.echo(f"  {step}", err=True)
    click.echo(f"error: could not find app {name!r}", err=True)
    if hints:
        click.echo(f"  similar: {', '.join(hints)}", err=True)
    sys.exit(1)


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
            ns = data.get("metadata", {}).get("namespace")
            if ns:
                return ns
        except SystemExit:
            continue
    return None
