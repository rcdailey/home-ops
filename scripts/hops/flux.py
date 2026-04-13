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


def _resolve_hr(name: str, namespace: str | None) -> dict:
    """Resolve a HelmRelease by name, returning the resource dict."""
    if namespace:
        return run_json(
            ["kubectl", "get", "helmrelease", name, "-n", namespace, "-o", "json"],
            timeout=15,
        )
    all_data = run_json(
        ["kubectl", "get", "helmreleases", "--all-namespaces", "-o", "json"],
        timeout=15,
    )
    matches = [i for i in all_data.get("items", []) if i["metadata"]["name"] == name]
    if not matches:
        info(f"error: HelmRelease {name!r} not found")
        raise SystemExit(1)
    return matches[0]


def _helm_chart_args(hr: dict) -> list[str]:
    """Build args for 'helm show values' from a HelmRelease's chart source."""
    meta = hr.get("metadata", {})
    hr_name = meta.get("name", "")
    hr_ns = meta.get("namespace", "")
    status = hr.get("status", {})
    last_revision = status.get("lastAppliedRevision", "")

    spec = hr.get("spec", {})
    chart_ref = spec.get("chartRef", {})
    chart_spec = spec.get("chart", {}).get("spec", {})

    if chart_ref:
        ref_name = chart_ref.get("name", "")
        ref_ns = chart_ref.get("namespace", hr_ns)
        ref_kind = chart_ref.get("kind", "OCIRepository")

        if ref_kind == "OCIRepository":
            oci_data = run_json(
                [
                    "kubectl",
                    "get",
                    "ocirepository",
                    ref_name,
                    "-n",
                    ref_ns,
                    "-o",
                    "json",
                ],
                timeout=10,
            )
            url = oci_data.get("spec", {}).get("url", "")
            tag = oci_data.get("spec", {}).get("ref", {}).get("tag", "")
            if url and tag:
                return [f"{url}:{tag}"]

    if chart_spec:
        chart = chart_spec.get("chart", "")
        version = chart_spec.get("version", "")
        source_ref = chart_spec.get("sourceRef", {})
        src_name = source_ref.get("name", "")
        src_ns = source_ref.get("namespace", hr_ns)
        src_kind = source_ref.get("kind", "HelmRepository")

        if src_kind == "HelmRepository":
            repo_data = run_json(
                [
                    "kubectl",
                    "get",
                    "helmrepository",
                    src_name,
                    "-n",
                    src_ns,
                    "-o",
                    "json",
                ],
                timeout=10,
            )
            repo_url = repo_data.get("spec", {}).get("url", "")

            if repo_url.startswith("oci://"):
                ref = f"{repo_url}/{chart}"
                if version:
                    ref += f":{version}"
                elif last_revision:
                    ref += f":{last_revision}"
                return [ref]
            else:
                args = [chart, "--repo", repo_url]
                if version:
                    args.extend(["--version", version])
                return args

    info(f"error: could not resolve chart source for {hr_name}")
    raise SystemExit(1)


@cli.command("values")
@click.argument("name")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (searches all if omitted)"
)
def values(name: str, namespace: str | None):
    """User-supplied value overrides for a HelmRelease."""
    hr = _resolve_hr(name, namespace)
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

    hr = _resolve_hr(name, namespace)
    chart_args = _helm_chart_args(hr)

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
        _print_yaml_key(output, key)
    elif search_term:
        _print_search_results(output, search_term)


def _print_yaml_key(yaml_text: str, key_path: str):
    """Extract a YAML subtree by dotted key path using yq."""
    import subprocess

    yq_expr = "." + ".".join(key_path.split("."))

    proc = subprocess.run(
        ["yq", yq_expr],
        input=yaml_text,
        capture_output=True,
        text=True,
        timeout=10,
    )

    if proc.returncode != 0:
        _print_yaml_key_naive(yaml_text, key_path)
        return

    output = (proc.stdout or "").strip()
    if output and output != "null":
        print(output)
    else:
        info(f"(key {key_path!r} not found in defaults)")


def _print_yaml_key_naive(yaml_text: str, key_path: str):
    """Extract a YAML subtree without yq (indent-based heuristic)."""
    parts = key_path.split(".")
    lines = yaml_text.split("\n")
    depth = 0
    capturing = False
    capture_indent = -1
    result_lines: list[str] = []

    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            if capturing:
                result_lines.append(line)
            continue

        indent = len(line) - len(stripped)

        if capturing:
            if indent > capture_indent:
                result_lines.append(line)
            else:
                break
        else:
            expected_key = parts[depth] + ":"
            if stripped.startswith(expected_key) and indent == depth * 2:
                depth += 1
                if depth == len(parts):
                    after_key = stripped[len(expected_key) :].strip()
                    if after_key and not after_key.startswith("#"):
                        info(f"{key_path}: {after_key}")
                        return
                    capturing = True
                    capture_indent = indent

    if result_lines:
        min_indent = min(
            len(ln) - len(ln.lstrip()) for ln in result_lines if ln.strip()
        )
        for line in result_lines:
            print(line[min_indent:] if line.strip() else "")
    else:
        info(f"(key {key_path!r} not found in defaults)")


def _print_search_results(yaml_text: str, term: str):
    """Search YAML text for a term, showing matching lines with context."""
    lines = yaml_text.split("\n")
    term_lower = term.lower()
    matches = []

    for i, line in enumerate(lines):
        if term_lower in line.lower():
            start = max(0, i - 2)
            end = min(len(lines), i + 3)
            matches.append((start, end))

    if not matches:
        info(f"(no matches for {term!r} in defaults)")
        return

    # Merge overlapping ranges
    merged = [matches[0]]
    for start, end in matches[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))

    for i, (start, end) in enumerate(merged):
        if i > 0:
            info("---")
        for j in range(start, end):
            print(f"{j + 1}: {lines[j]}")


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
