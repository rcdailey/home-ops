"""Correlate zero-target vmagent pools with live scrape resources."""

from __future__ import annotations

import json
from typing import Any

import click

from hops.core.format import info, table
from hops.core.runner import kubectl_json
from hops.query._vm import query_vm

_SCRAPE_RESOURCES = (
    "vmservicescrapes,vmpodscrapes,vmnodescrapes,vmprobes,vmstaticscrapes"
)
_POOL_KINDS = {
    "serviceScrape": "VMServiceScrape",
    "podScrape": "VMPodScrape",
    "nodeScrape": "VMNodeScrape",
    "probe": "VMProbe",
    "staticScrape": "VMStaticScrape",
}


def _resource_key(item: dict[str, Any]) -> tuple[str, str, str]:
    metadata = item.get("metadata", {})
    return item.get("kind", ""), metadata.get("namespace", ""), metadata.get("name", "")


def _pool_key(pool: str) -> tuple[str, str, str] | None:
    parts = pool.split("/")
    if len(parts) < 3 or parts[0] not in _POOL_KINDS:
        return None
    return _POOL_KINDS[parts[0]], parts[1], parts[2]


def _owner(resource: dict[str, Any]) -> str:
    owners = resource.get("metadata", {}).get("ownerReferences", [])
    if not owners:
        return "-"
    return ",".join(
        f"{owner.get('kind', '?')}/{owner.get('name', '?')}" for owner in owners
    )


@click.command("scrape-pools")
@click.option("-n", "--namespace", help="Filter by scrape resource namespace")
@click.option(
    "--json", "as_json", is_flag=True, help="Output correlated findings as JSON"
)
def scrape_pools(namespace: str | None, as_json: bool) -> None:
    """Show zero-target pools with their live scrape resources and owners."""
    data = query_vm(
        "/api/v1/query",
        {"query": ("sum by (scrape_job) (vm_promscrape_scrape_pool_targets) == 0")},
    )
    pools = sorted(
        {
            result.get("metric", {}).get("scrape_job", "")
            for result in data.get("data", {}).get("result", [])
            if result.get("metric", {}).get("scrape_job")
        }
    )
    resources = kubectl_json(_SCRAPE_RESOURCES).get("items", [])
    resource_index = {_resource_key(item): item for item in resources}

    findings = []
    for pool in pools:
        key = _pool_key(pool)
        if namespace and (not key or key[1] != namespace):
            continue
        if not key:
            findings.append({"pool": pool, "resource": None, "state": "STALE"})
            continue
        resource = resource_index.get(key)
        if not resource:
            findings.append({"pool": pool, "resource": None, "state": "STALE"})
            continue
        owner = _owner(resource)
        state = "ORPHAN" if owner == "-" else "OWNED"
        findings.append(
            {"pool": pool, "resource": resource, "owner": owner, "state": state}
        )

    if as_json:
        click.echo(json.dumps(findings, indent=2))
        return

    if not findings:
        suffix = f" in namespace {namespace}" if namespace else ""
        info(f"No zero-target scrape pools{suffix}")
        return

    rows = []
    for finding in findings:
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

    info(f"Zero-target scrape pools: {len(findings)}")
    table(["POOL", "LIVE RESOURCE", "OWNER", "STATE"], rows)
