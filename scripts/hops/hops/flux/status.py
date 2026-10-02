"""Flux read-only status commands: status, values, defaults."""

from __future__ import annotations

import click

from hops.core.format import info, table, truncate
from hops.core.helm import (
    helm_chart_args,
    print_search_results,
    print_yaml_key,
    resolve_hr,
)
from hops.core.runner import run, run_json
from hops.flux import cli


@cli.command("status")
@click.argument("names", nargs=-1)
def flux_status(names: tuple[str, ...]):
    """Flux resource status. NAMES filters by exact or substring match.

    Without NAMES: problems only (unhealthy Kustomizations and HelmReleases).
    With one or more NAMES: show matching resources regardless of health state.
    """
    all_resources: list[dict] = []
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
            item["_kind_label"] = label
        all_resources.extend(items)

    if names:
        matches: list[dict] = []
        missing: list[str] = []
        for name in names:
            found = _find_items(all_resources, name)
            if found:
                matches.extend(found)
            else:
                missing.append(name)

        # Deduplicate (same resource matched by multiple names)
        seen: set[tuple[str, str, str]] = set()
        unique: list[dict] = []
        for item in matches:
            key = (
                item["_kind_label"],
                item["metadata"]["namespace"],
                item["metadata"]["name"],
            )
            if key not in seen:
                seen.add(key)
                unique.append(item)

        if unique:
            rows = []
            for item in sorted(
                unique,
                key=lambda i: (
                    i["metadata"]["namespace"],
                    i["metadata"]["name"],
                ),
            ):
                meta = item["metadata"]
                rows.append(
                    [
                        item["_kind_label"],
                        meta["namespace"],
                        meta["name"],
                        _ready_status(item),
                    ]
                )
            table(["TYPE", "NAMESPACE", "NAME", "STATUS"], rows)
        if missing:
            for name in missing:
                info(f"not found: {name}")
            if not unique:
                raise SystemExit(1)
        return

    problems = []
    for item in all_resources:
        meta = item["metadata"]
        conditions = item.get("status", {}).get("conditions", [])
        ready = None
        for cond in conditions:
            if cond.get("type") == "Ready":
                ready = cond
                break
        if ready and ready.get("status") != "True":
            msg = truncate(ready.get("message", ""), 100)
            problems.append(
                [item["_kind_label"], meta["namespace"], meta["name"], "Not Ready", msg]
            )
        elif not ready:
            problems.append(
                [
                    item["_kind_label"],
                    meta["namespace"],
                    meta["name"],
                    "Unknown",
                    "no Ready condition",
                ]
            )

    if not problems:
        ks = totals.get("Kustomization", 0)
        hr = totals.get("HelmRelease", 0)
        info(f"All {ks} Kustomizations and {hr} HelmReleases are Ready.")
        return

    table(
        ["TYPE", "NAMESPACE", "NAME", "STATUS", "MESSAGE"],
        problems,
    )


def _ready_status(item: dict) -> str:
    """Extract compact Ready status from a Flux resource."""
    for cond in item.get("status", {}).get("conditions", []):
        if cond.get("type") == "Ready":
            if cond.get("status") == "True":
                return "Ready"
            return truncate(cond.get("message", "Not Ready"), 80)
    return "Unknown"


def _find_items(items: list[dict], name: str | None) -> list[dict]:
    """Filter items: exact match first, then substring, then all."""
    if not name:
        return items
    exact = [i for i in items if i["metadata"]["name"] == name]
    if exact:
        return exact
    return [i for i in items if name in i["metadata"]["name"]]


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
        click.echo(output)
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
