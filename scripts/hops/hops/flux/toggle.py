"""Flux suspend/resume commands.

Controlled exception to hops read-only rule. Flux suspend/resume is
a reversible state toggle needed during storage migrations, chart
upgrades with immutable fields, and other maintenance. The workflow
finds the resource namespace automatically and handles both
Kustomization + HelmRelease in one call so callers avoid the
namespace-hunting and dual-command dance.
"""

from __future__ import annotations

import click

from hops.core.format import info
from hops.core.runner import run, run_json
from hops.flux import cli


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
