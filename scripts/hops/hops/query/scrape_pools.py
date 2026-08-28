"""Correlate OpenTelemetry scrape assignments with live monitor resources."""

from __future__ import annotations

import json
from typing import Any

import click

from hops.core.format import age_str, info, table, truncate
from hops.core.runner import kubectl_json
from hops.query._vm import query_target_allocator
from hops.query.scrape_health import active_target_health, target_identity

_SCRAPE_RESOURCES = "servicemonitors,podmonitors"
_POOL_KINDS = {
    "serviceMonitor": "ServiceMonitor",
    "podMonitor": "PodMonitor",
}


def _resource_key(item: dict[str, Any]) -> tuple[str, str, str]:
    metadata = item.get("metadata", {})
    return item.get("kind", ""), metadata.get("namespace", ""), metadata.get("name", "")


def _pool_key(pool: str) -> tuple[str, str, str] | None:
    parts = pool.split("/")
    if len(parts) < 3 or parts[0] not in _POOL_KINDS:
        return None
    return _POOL_KINDS[parts[0]], parts[1], parts[2]


def _target_count(assignments: dict[str, Any]) -> int:
    """Count endpoints assigned across all scrape collectors."""
    return sum(
        len(target.get("targets", []))
        for collector in assignments.values()
        for target in collector.get("targets", [])
    )


def _owner(resource: dict[str, Any]) -> str:
    owners = resource.get("metadata", {}).get("ownerReferences", [])
    if not owners:
        return "-"
    return ",".join(
        f"{owner.get('kind', '?')}/{owner.get('name', '?')}" for owner in owners
    )


@click.command("scrapes")
@click.option("-n", "--namespace", help="Filter by scrape resource namespace")
@click.option(
    "--json", "as_json", is_flag=True, help="Output correlated findings as JSON"
)
def scrapes(namespace: str | None, as_json: bool) -> None:
    """Show failed targets and zero-target pools with owning resources."""
    target_count, unhealthy_targets = active_target_health(namespace)
    jobs = query_target_allocator("/jobs")
    pools = []
    for pool, job in jobs.items():
        assignments = query_target_allocator(job.get("_link", f"/jobs/{pool}/targets"))
        if _target_count(assignments) == 0:
            pools.append(pool)
    pools.sort()
    resources = kubectl_json(_SCRAPE_RESOURCES).get("items", [])
    resource_index = {_resource_key(item): item for item in resources}

    pool_findings = []
    for pool in pools:
        key = _pool_key(pool)
        if namespace and (not key or key[1] != namespace):
            continue
        if not key:
            pool_findings.append({"pool": pool, "resource": None, "state": "STATIC"})
            continue
        resource = resource_index.get(key)
        if not resource:
            pool_findings.append({"pool": pool, "resource": None, "state": "STALE"})
            continue
        owner = _owner(resource)
        state = "DIRECT" if owner == "-" else "OWNED"
        pool_findings.append(
            {"pool": pool, "resource": resource, "owner": owner, "state": state}
        )

    if as_json:
        click.echo(
            json.dumps(
                {
                    "activeTargetCount": target_count,
                    "unhealthyTargets": unhealthy_targets,
                    "zeroTargetPools": pool_findings,
                },
                indent=2,
            )
        )
        return

    if not unhealthy_targets and not pool_findings:
        suffix = f" in namespace {namespace}" if namespace else ""
        if not target_count:
            info(f"No active scrape targets{suffix}.")
            return
        info(
            f"All {target_count} active scrape targets healthy; no zero-target pools{suffix}."
        )
        return

    if unhealthy_targets:
        info(f"Unhealthy scrape targets: {len(unhealthy_targets)}/{target_count}")
        rows = []
        for target in unhealthy_targets:
            rows.append(
                [
                    target.get("scrapePool", "?"),
                    target_identity(target),
                    age_str(target.get("lastScrape")),
                    truncate(target.get("lastError", "unknown error")),
                ]
            )
        table(["POOL", "TARGET", "LAST", "ERROR"], rows)

    rows = []
    for finding in pool_findings:
        resource = finding["resource"]
        live_resource = "-"
        if resource:
            kind, resource_namespace, name = _resource_key(resource)
            live_resource = f"{kind}/{resource_namespace}/{name}"
        rows.append(
            [
                finding["pool"],
                live_resource,
                finding.get("owner", "-"),
                finding["state"],
            ]
        )

    if rows:
        info(f"Zero-target scrape pools: {len(pool_findings)}")
        table(["POOL", "LIVE RESOURCE", "OWNER", "STATE"], rows)
