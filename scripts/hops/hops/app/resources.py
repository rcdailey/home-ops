"""App resource usage compared with container requests and limits."""

from __future__ import annotations

import click

from hops.app import cli
from hops.core.format import info, table
from hops.core.runner import kubectl_json, run
from hops.core.workload import resolve_app, suggest_near_matches


@cli.command()
@click.argument("app")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (auto-detected if omitted)"
)
def resources(app: str, namespace: str | None):
    """Pod resource usage vs requests/limits for an app."""
    wl = resolve_app(app, namespace)
    if not wl:
        hints = suggest_near_matches(app, namespace)
        info(f"error: could not find app {app!r}")
        if hints:
            info(f"  similar: {', '.join(hints)}")
        raise SystemExit(1)

    spec_data = kubectl_json("pods", namespace=wl.namespace)
    pod_specs: dict[str, list[dict]] = {}
    for item in spec_data.get("items", []):
        name = item["metadata"]["name"]
        if name.startswith(wl.name):
            pod_specs[name] = item.get("spec", {}).get("containers", [])

    if not pod_specs:
        info(f"No pods found for {wl.name!r} in {wl.namespace}")
        return

    usage_map: dict[str, dict[str, dict]] = {}
    try:
        result = run(
            [
                "kubectl",
                "top",
                "pods",
                "-n",
                wl.namespace,
                "--no-headers",
                "--containers",
            ],
            timeout=15,
            check=False,
        )
        if result.returncode == 0 and result.stdout:
            for line in result.stdout.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 4:
                    pname, cname, cpu, mem = parts[0], parts[1], parts[2], parts[3]
                    if pname.startswith(wl.name):
                        usage_map.setdefault(pname, {})[cname] = {
                            "cpu": cpu,
                            "memory": mem,
                        }
    except SystemExit:
        pass

    rows = []
    for pod_name in sorted(pod_specs):
        for container in pod_specs[pod_name]:
            cname = container.get("name", "")
            res = container.get("resources", {})
            req = res.get("requests", {})
            lim = res.get("limits", {})
            usage = usage_map.get(pod_name, {}).get(cname, {})
            rows.append(
                [
                    pod_name,
                    cname,
                    usage.get("cpu", "-"),
                    req.get("cpu", "-"),
                    lim.get("cpu", "-"),
                    usage.get("memory", "-"),
                    req.get("memory", "-"),
                    lim.get("memory", "-"),
                ]
            )

    table(
        [
            "POD",
            "CONTAINER",
            "CPU.use",
            "CPU.req",
            "CPU.lim",
            "MEM.use",
            "MEM.req",
            "MEM.lim",
        ],
        rows,
    )
