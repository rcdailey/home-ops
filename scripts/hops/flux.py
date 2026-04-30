"""Flux domain: GitOps reconciliation status and diagnostics."""

from __future__ import annotations

import click

from hops._format import info, kv, table, truncate
from hops._helm import helm_chart_args, print_search_results, print_yaml_key, resolve_hr
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


@cli.command("values")
@click.argument("name")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (searches all if omitted)"
)
def values(name: str, namespace: str | None):
    """User-supplied value overrides for a HelmRelease."""
    hr = resolve_hr(name, namespace)
    hr_ns = hr.get("metadata", {}).get("namespace", "")

    result = run(
        ["helm", "get", "values", name, "-n", hr_ns, "-o", "yaml"],
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        msg = (result.stderr or "").strip().split("\n")[0]
        info(f"error: {msg}")
        raise SystemExit(1)

    output = (result.stdout or "").strip()
    if output and output != "null":
        print(output)
    else:
        info("(no user-supplied values)")


@cli.command("defaults")
@click.argument("name")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (searches all if omitted)"
)
@click.option(
    "--key", default=None, help="YAML key path to extract (e.g., config.envoyGateway)"
)
@click.option(
    "--search", "search_term", default=None, help="Search defaults for a keyword"
)
def defaults(
    name: str, namespace: str | None, key: str | None, search_term: str | None
):
    """Chart default values for a HelmRelease (scoped).

    Requires --key or --search to avoid dumping thousands of lines.
    Use --key to extract a subtree, --search to find matching lines.
    """
    if not key and not search_term:
        info("error: specify --key <path> or --search <term> to scope output")
        info("  --key config.envoyGateway    extract a subtree")
        info("  --search enableBackend       find matching lines with context")
        raise SystemExit(1)

    hr = resolve_hr(name, namespace)
    chart_args = helm_chart_args(hr)

    result = run(
        ["helm", "show", "values", *chart_args],
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        msg = (result.stderr or "").strip().split("\n")[0]
        info(f"error: {msg}")
        raise SystemExit(1)

    output = (result.stdout or "").strip()
    if not output:
        info("(no default values)")
        return

    if key:
        print_yaml_key(output, key)
    elif search_term:
        print_search_results(output, search_term)


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


# -- Suspend / Resume --
# Controlled exception to hops read-only rule. Flux suspend/resume is
# a reversible state toggle needed during storage migrations, chart
# upgrades with immutable fields, and other maintenance. The workflow
# finds the resource namespace automatically and handles both
# Kustomization + HelmRelease in one call so callers avoid the
# namespace-hunting and dual-command dance.


def _find_flux_resource(
    kind: str, name: str, namespace: str | None
) -> tuple[str, str] | None:
    """Find a Flux resource by name, returning (namespace, name) or None."""
    if namespace:
        result = run(
            ["kubectl", "get", kind, name, "-n", namespace, "-o", "name"],
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            return namespace, name
        return None

    # Search all namespaces
    all_data = run_json(
        ["kubectl", "get", kind, "--all-namespaces", "-o", "json"],
        timeout=15,
        quiet=True,
    )
    for item in all_data.get("items", []):
        if item["metadata"]["name"] == name:
            return item["metadata"]["namespace"], name
    return None


def _flux_toggle(name: str, namespace: str | None, action: str):
    """Suspend or resume Flux Kustomization + HelmRelease for an app.

    Finds resources across namespaces, handles both resource types,
    and reports what was changed.
    """
    acted = []

    ks = _find_flux_resource(
        "kustomization.kustomize.toolkit.fluxcd.io", name, namespace
    )
    if ks:
        ks_ns, ks_name = ks
        result = run(
            ["flux", action, "kustomization", ks_name, "-n", ks_ns],
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            acted.append(f"Kustomization/{ks_name} in {ks_ns}")
        else:
            msg = (result.stderr or "").strip().split("\n")[0]
            info(f"error: flux {action} kustomization {ks_name}: {msg}")

    # HelmRelease may be in a different namespace (targetNamespace)
    hr_ns = namespace
    if ks and not hr_ns:
        ks_data = run_json(
            [
                "kubectl",
                "get",
                "kustomization.kustomize.toolkit.fluxcd.io",
                ks[1],
                "-n",
                ks[0],
                "-o",
                "json",
            ],
            timeout=10,
            quiet=True,
        )
        target = ks_data.get("spec", {}).get("targetNamespace")
        if target:
            hr_ns = target

    hr = _find_flux_resource("helmrelease.helm.toolkit.fluxcd.io", name, hr_ns)
    if hr:
        hr_real_ns, hr_name = hr
        result = run(
            ["flux", action, "helmrelease", hr_name, "-n", hr_real_ns],
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            acted.append(f"HelmRelease/{hr_name} in {hr_real_ns}")
        else:
            msg = (result.stderr or "").strip().split("\n")[0]
            info(f"error: flux {action} helmrelease {hr_name}: {msg}")

    if not acted:
        info(f"error: no Kustomization or HelmRelease named {name!r} found")
        raise SystemExit(1)

    verb = "suspended" if action == "suspend" else "resumed"
    for item in acted:
        info(f"{verb}: {item}")


@cli.command("suspend")
@click.argument("name")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (searches all if omitted)"
)
def suspend(name: str, namespace: str | None):
    """Suspend Flux reconciliation for an app (Kustomization + HelmRelease).

    Finds both resources automatically across namespaces. Use before
    imperative cleanup (storage migrations, immutable field changes).
    """
    _flux_toggle(name, namespace, "suspend")


@cli.command("resume")
@click.argument("name")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (searches all if omitted)"
)
def resume(name: str, namespace: str | None):
    """Resume Flux reconciliation for an app (Kustomization + HelmRelease).

    Counterpart to 'suspend'. Finds both resources and resumes them.
    """
    _flux_toggle(name, namespace, "resume")
