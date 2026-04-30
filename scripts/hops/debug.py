"""Debug domain: ephemeral pod workflows and gateway diagnostics."""

from __future__ import annotations

import os
import sys

import click

from hops._format import info, kv, section, table, truncate
from hops._gateway import (
    extract_policy_details,
    fetch_envoy_proxy,
    fetch_gateway,
    find_httproute,
    find_policies_for_gateway,
    find_security_policies,
    search_envoy_errors,
)
from hops._runner import run


def _pod_name(prefix: str) -> str:
    return f"hops-{prefix}-{os.getpid()}"


def _run_ephemeral(
    image: str,
    command: list[str],
    *,
    name: str,
    namespace: str = "default",
    timeout: int = 30,
) -> None:
    """Create a pod, wait for completion, capture logs, clean up."""
    create_args = [
        "kubectl",
        "run",
        name,
        "--image",
        image,
        "--restart=Never",
        "--namespace",
        namespace,
        "--override-type=strategic",
        "--overrides",
        '{"spec":{"terminationGracePeriodSeconds":0}}',
        "--command",
        "--",
    ] + command

    try:
        result = run(create_args, timeout=timeout, check=False)
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            info(f"error: failed to create pod: {stderr}")
            return

        run(
            [
                "kubectl",
                "wait",
                f"pod/{name}",
                "-n",
                namespace,
                "--for=jsonpath={.status.phase}=Succeeded",
                f"--timeout={timeout}s",
            ],
            timeout=timeout + 5,
            check=False,
        )

        log_result = run(
            ["kubectl", "logs", name, "-n", namespace],
            timeout=15,
            check=False,
        )
        if log_result.stdout:
            print(log_result.stdout.rstrip())
        if log_result.stderr and log_result.returncode != 0:
            print(log_result.stderr.rstrip(), file=sys.stderr)

    finally:
        run(
            [
                "kubectl",
                "delete",
                "pod",
                name,
                "-n",
                namespace,
                "--grace-period=0",
                "--force",
                "--wait=false",
            ],
            timeout=10,
            check=False,
        )


@click.group()
def cli():
    """Ephemeral debug pods and gateway diagnostics."""


@cli.command()
@click.argument("hostname")
@click.option("-n", "--namespace", default="default", help="Namespace to run in")
def dns(hostname: str, namespace: str):
    """DNS lookup via ephemeral busybox pod."""
    name = _pod_name("dns")
    info(f"Resolving {hostname} ...")
    _run_ephemeral(
        image="busybox:stable",
        command=["nslookup", hostname],
        name=name,
        namespace=namespace,
    )


@cli.command()
@click.argument("url")
@click.option("-n", "--namespace", default="default", help="Namespace to run in")
@click.option("--method", default="GET", help="HTTP method")
def curl(url: str, namespace: str, method: str):
    """HTTP request via ephemeral curlimages/curl pod."""
    name = _pod_name("curl")
    info(f"{method} {url} ...")
    _run_ephemeral(
        image="curlimages/curl:latest",
        command=[
            "curl",
            "-sS",
            "-X",
            method,
            "-o",
            "/dev/null",
            "-w",
            "HTTP %{http_code} (%{time_total}s, %{size_download} bytes)\n",
            url,
        ],
        name=name,
        namespace=namespace,
    )


@cli.command()
@click.argument("app")
@click.option(
    "-n", "--namespace", default=None, help="Namespace (auto-detected if omitted)"
)
@click.option("--errors", default=10, help="Max envoy error log entries (default: 10)")
def route(app: str, namespace: str | None, errors: int):
    """Trace an app's request path through the gateway.

    Correlates HTTPRoute, Gateway, traffic policies, security policies,
    and envoy access log errors. Accepts an app name, HTTPRoute name,
    or hostname substring.
    """
    rt = find_httproute(app, namespace)
    if not rt:
        info(f"error: no HTTPRoute matching {app!r}")
        raise SystemExit(1)

    meta = rt.get("metadata", {})
    rt_name = meta.get("name", "?")
    rt_ns = meta.get("namespace", "?")
    spec = rt.get("spec", {})
    hostnames = spec.get("hostnames", [])

    # HTTPRoute summary
    section("HTTPROUTE")
    kv(
        [
            ("name", rt_name),
            ("namespace", rt_ns),
            ("hostnames", ", ".join(hostnames) if hostnames else "(none)"),
        ]
    )

    for rule in spec.get("rules", []):
        for ref in rule.get("backendRefs", []):
            kind = ref.get("kind", "Service")
            name = ref.get("name", "?")
            port = ref.get("port", "?")
            info(f"  backendRef: {kind}/{name}:{port}")

    parents = rt.get("status", {}).get("parents", [])
    for parent in parents:
        gw_ref = parent.get("parentRef", {})
        gw_name = gw_ref.get("name", "?")
        gw_section = gw_ref.get("sectionName", "")
        info(f"  gateway: {gw_name}" + (f" ({gw_section})" if gw_section else ""))
        for cond in parent.get("conditions", []):
            ctype = cond.get("type", "?")
            cstatus = "yes" if cond.get("status") == "True" else "no"
            info(f"    {ctype}: {cstatus}")

    # Find parent Gateway (single fetch, reused for policies + envoyproxy)
    gw_name = None
    gw_ns = None
    for parent in parents:
        gw_ref = parent.get("parentRef", {})
        gw_name = gw_ref.get("name")
        gw_ns = gw_ref.get("namespace", rt_ns)
        if gw_name:
            break

    if gw_name and gw_ns:
        gw_data = fetch_gateway(gw_name, gw_ns)

        # Gateway details
        section("GATEWAY")
        if gw_data:
            gw_class = gw_data.get("spec", {}).get("gatewayClassName", "?")
            listeners = gw_data.get("spec", {}).get("listeners", [])
            listener_strs = [
                f"{ln.get('name', '?')}:{ln.get('port', '?')}/{ln.get('protocol', '?')}"
                for ln in listeners
            ]
            kv(
                [
                    ("name", gw_name),
                    ("class", gw_class),
                    (
                        "listeners",
                        ", ".join(listener_strs) if listener_strs else "(none)",
                    ),
                ]
            )
        else:
            info(f"Gateway: {gw_name} (not found)")

        # Traffic policies
        section("POLICIES")
        policies = find_policies_for_gateway(gw_name, gw_ns)
        if not policies:
            info("(no traffic policies attached)")
        for kind, items in policies.items():
            label = (
                "ClientTrafficPolicy" if "client" in kind else "BackendTrafficPolicy"
            )
            for pol in items:
                pol_name = pol.get("metadata", {}).get("name", "?")
                pol_ns = pol.get("metadata", {}).get("namespace", "?")
                info(f"{label}: {pol_name} ({pol_ns})")
                details = extract_policy_details(pol)
                if details:
                    kv(details, indent=2)
                else:
                    info("  (default settings)")

        # Security policies on the route
        sec_policies = find_security_policies(rt_name, rt_ns)
        if sec_policies:
            for sp in sec_policies:
                sp_name = sp.get("metadata", {}).get("name", "?")
                info(f"SecurityPolicy: {sp_name}")

        # EnvoyProxy config (traced from the already-fetched gateway)
        if gw_data:
            ep_result = fetch_envoy_proxy(gw_data, gw_ns)
            if ep_result:
                ep_name, ep_spec = ep_result
                log_level = (
                    ep_spec.get("logging", {}).get("level", {}).get("default", "?")
                )
                replicas = (
                    ep_spec.get("provider", {})
                    .get("kubernetes", {})
                    .get("envoyDeployment", {})
                    .get("replicas", "?")
                )
                info(f"EnvoyProxy: {ep_name}")
                kv(
                    [
                        ("replicas", str(replicas)),
                        ("logLevel", log_level),
                    ],
                    indent=2,
                )

    # Envoy access log errors
    if hostnames:
        section("ENVOY ERRORS (recent)")
        error_entries = search_envoy_errors(hostnames, limit=errors)
        if not error_entries:
            info("(no recent errors)")
        else:
            rows = []
            for entry in error_entries:
                code = str(entry.get("response_code", "?"))
                method = entry.get("method", "?")
                path = truncate(entry.get("x-envoy-origin-path", "?"), 60)
                flags = entry.get("response_flags", "-")
                detail = entry.get("response_code_details", "-")
                duration = entry.get("duration", "?")
                sent = entry.get("bytes_sent", "?")
                recv = entry.get("bytes_received", "?")
                rows.append(
                    [
                        code,
                        method,
                        path,
                        str(duration) + "ms",
                        flags,
                        detail,
                        f"rx={recv} tx={sent}",
                    ]
                )
            table(
                ["CODE", "METHOD", "PATH", "DUR", "FLAGS", "DETAIL", "BYTES"],
                rows,
            )
