"""Service address lookup: in-cluster hostnames and the routes that reach them."""

from __future__ import annotations

import click

from hops.app import cli
from hops.core.format import info, table
from hops.core.runner import kubectl_json


def match_services(app_name: str, ns: str | None) -> list[dict]:
    """Services belonging to an app.

    Substring matching is deliberate. Operator-generated services prefix the
    release name rather than suffixing it (vmalertmanager-<release>), so
    anchoring on a name prefix or an exact app label misses exactly the
    services a caller cannot guess and therefore most needs looked up.
    """
    needle = app_name.lower()
    matches = []
    for item in kubectl_json("services", namespace=ns).get("items", []):
        meta = item.get("metadata", {})
        labels = meta.get("labels", {})
        name = meta.get("name", "")
        if (
            needle in name.lower()
            or labels.get("app.kubernetes.io/name") == app_name
            or labels.get("app.kubernetes.io/instance") == app_name
        ):
            matches.append(item)
    return matches


def _route_hostnames(services: list[dict], ns: str | None) -> list[list[str]]:
    """External hostnames whose HTTPRoutes point at any of these services."""
    wanted = {(s["metadata"]["name"], s["metadata"]["namespace"]) for s in services}
    rows = []
    for route in kubectl_json("httproutes", namespace=ns).get("items", []):
        route_ns = route["metadata"].get("namespace", "")
        backends = [
            ref.get("name", "")
            for rule in route.get("spec", {}).get("rules", [])
            for ref in rule.get("backendRefs", [])
        ]
        hit = next((b for b in backends if (b, route_ns) in wanted), None)
        if not hit:
            continue
        for hostname in route.get("spec", {}).get("hostnames", []):
            rows.append([hostname, hit])
    return rows


@cli.command("addr")
@click.argument("app")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (searches all if omitted)"
)
def addr(app: str, namespace: str | None):
    """In-cluster addresses for an app, plus any external hostnames."""
    services = match_services(app, namespace)
    if not services:
        info(f"error: no service matching {app!r}")
        raise SystemExit(1)

    rows = []
    for svc in sorted(services, key=lambda s: s["metadata"]["name"]):
        meta = svc["metadata"]
        spec = svc.get("spec", {})
        stype = spec.get("type", "ClusterIP")
        for port in spec.get("ports", []):
            rows.append(
                [
                    f"{meta['name']}.{meta['namespace']}:{port.get('port', '?')}",
                    port.get("name", "-"),
                    stype if stype != "ClusterIP" else "-",
                ]
            )
    table(["ADDRESS", "PORT", "TYPE"], rows)

    external = _route_hostnames(services, namespace)
    if external:
        click.echo("\nExternal:")
        table(["HOSTNAME", "BACKEND"], external)
