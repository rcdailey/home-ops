"""Flux domain: GitOps reconciliation status and diagnostics."""

from __future__ import annotations

import click

from hops._format import info, kv, table, truncate
from hops._runner import run, run_json


@click.group()
def cli():
    """Flux GitOps status and diagnostics."""


@cli.command("status")
def flux_status():
    """Problems only: unhealthy Kustomizations and HelmReleases.

    Shows only resources that are not Ready. If everything is healthy,
    says so in one line.
    """
    problems = []
    totals = {}

    for kind, label in [
        ("kustomizations", "Kustomization"),
        ("helmreleases", "HelmRelease"),
    ]:
        data = run_json(
            ["kubectl", "get", kind, "--all-namespaces", "-o", "json"],
            timeout=30,
        )
        items = data.get("items", [])
        totals[label] = len(items)
        for item in items:
            meta = item.get("metadata", {})
            name = meta.get("name", "")
            ns = meta.get("namespace", "")
            conditions = item.get("status", {}).get("conditions", [])
            ready = None
            for cond in conditions:
                if cond.get("type") == "Ready":
                    ready = cond
                    break
            if ready and ready.get("status") != "True":
                msg = truncate(ready.get("message", ""), 100)
                problems.append([label, ns, name, "Not Ready", msg])
            elif not ready:
                problems.append([label, ns, name, "Unknown", "no Ready condition"])

    if not problems:
        ks = totals.get("Kustomization", 0)
        hr = totals.get("HelmRelease", 0)
        info(f"All {ks} Kustomizations and {hr} HelmReleases are Ready.")
        return

    table(
        ["TYPE", "NAMESPACE", "NAME", "STATUS", "MESSAGE"],
        problems,
    )


@cli.command("hr")
@click.argument("name")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (searches all if omitted)"
)
def helmrelease(name: str, namespace: str | None):
    """Detailed HelmRelease status."""
    if namespace:
        data = run_json(
            ["kubectl", "get", "helmrelease", name, "-n", namespace, "-o", "json"],
            timeout=15,
        )
    else:
        # Search all namespaces
        all_data = run_json(
            ["kubectl", "get", "helmreleases", "--all-namespaces", "-o", "json"],
            timeout=15,
        )
        matches = [
            i for i in all_data.get("items", []) if i["metadata"]["name"] == name
        ]
        if not matches:
            info(f"error: HelmRelease {name!r} not found")
            raise SystemExit(1)
        data = matches[0]

    meta = data.get("metadata", {})
    spec = data.get("spec", {})
    status = data.get("status", {})

    pairs = [
        ("Name", meta.get("name", "")),
        ("Namespace", meta.get("namespace", "")),
    ]

    # Chart info
    chart_ref = spec.get("chartRef", {})
    chart_spec = spec.get("chart", {}).get("spec", {})
    if chart_ref:
        pairs.append(("Chart", f"{chart_ref.get('name', '?')} (chartRef)"))
    elif chart_spec:
        pairs.append(
            ("Chart", f"{chart_spec.get('chart', '?')} {chart_spec.get('version', '')}")
        )

    pairs.append(("Revision", status.get("lastAppliedRevision", "?")))

    # Conditions
    conditions = status.get("conditions", [])
    for cond in conditions:
        ctype = cond.get("type", "")
        cstatus = cond.get("status", "")
        msg = cond.get("message", "")
        pairs.append((ctype, f"{cstatus} - {truncate(msg, 100)}" if msg else cstatus))

    kv(pairs)


@cli.command("ks")
@click.argument("name")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (searches all if omitted)"
)
def kustomization(name: str, namespace: str | None):
    """Detailed Kustomization status."""
    if namespace:
        data = run_json(
            ["kubectl", "get", "kustomization", name, "-n", namespace, "-o", "json"],
            timeout=15,
        )
    else:
        all_data = run_json(
            ["kubectl", "get", "kustomizations", "--all-namespaces", "-o", "json"],
            timeout=15,
        )
        matches = [
            i for i in all_data.get("items", []) if i["metadata"]["name"] == name
        ]
        if not matches:
            info(f"error: Kustomization {name!r} not found")
            raise SystemExit(1)
        data = matches[0]

    meta = data.get("metadata", {})
    spec = data.get("spec", {})
    status = data.get("status", {})

    pairs = [
        ("Name", meta.get("name", "")),
        ("Namespace", meta.get("namespace", "")),
        ("Path", spec.get("path", "?")),
        (
            "SourceRef",
            f"{spec.get('sourceRef', {}).get('kind', '?')}/{spec.get('sourceRef', {}).get('name', '?')}",
        ),
        ("Revision", status.get("lastAppliedRevision", "?")),
    ]

    # Target namespace
    target_ns = spec.get("targetNamespace")
    if target_ns:
        pairs.append(("TargetNS", target_ns))

    # Conditions
    conditions = status.get("conditions", [])
    for cond in conditions:
        ctype = cond.get("type", "")
        cstatus = cond.get("status", "")
        msg = cond.get("message", "")
        pairs.append((ctype, f"{cstatus} - {truncate(msg, 100)}" if msg else cstatus))

    kv(pairs)


@cli.command("test")
@click.argument("path", default="kubernetes/flux/cluster")
def flux_test(path: str):
    """Run flux-local test on the cluster configuration."""
    result = run(
        [
            "uvx",
            "flux-local",
            "test",
            "--enable-helm",
            "--all-namespaces",
            "--path",
            path,
        ],
        timeout=300,
        check=False,
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip())
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    else:
        info("flux-local test completed successfully")
