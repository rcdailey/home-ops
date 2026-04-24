"""Debug domain: ephemeral pod workflows and gateway diagnostics."""

from __future__ import annotations

import json
import os
import sys

import click

from hops._format import info, kv, section, table, truncate
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
        # Create the pod
        result = run(create_args, timeout=timeout, check=False)
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            info(f"error: failed to create pod: {stderr}")
            return

        # Wait for pod to complete (Succeeded or Failed)
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

        # Get logs
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
        # Always clean up
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


def _find_httproute(name: str, namespace: str | None) -> dict | None:
    """Find an HTTPRoute by name or hostname match.

    Strategy:
    1. List all HTTPRoutes; match by exact name, then hostname substring.
    2. When namespace is given, scope the search.
    """
    args = ["kubectl", "get", "httproute", "-o", "json"]
    if namespace:
        args.extend(["-n", namespace])
    else:
        args.append("-A")
    result = run(args, timeout=10, check=False)
    if result.returncode != 0 or not result.stdout:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    # Exact name match first
    for item in data.get("items", []):
        if item.get("metadata", {}).get("name") == name:
            return item

    # Hostname substring match
    for item in data.get("items", []):
        hostnames = item.get("spec", {}).get("hostnames", [])
        for h in hostnames:
            if name in h:
                return item
    return None


def _find_policies_for_gateway(gw_name: str, gw_ns: str) -> dict[str, list[dict]]:
    """Find ClientTrafficPolicy, BackendTrafficPolicy targeting a Gateway."""
    policies: dict[str, list[dict]] = {}
    for kind in ("clienttrafficpolicies", "backendtrafficpolicies"):
        args = ["kubectl", "get", kind, "-A", "-o", "json"]
        result = run(args, timeout=10, check=False)
        if result.returncode != 0 or not result.stdout:
            continue
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            continue
        for item in data.get("items", []):
            spec = item.get("spec", {})
            # Check targetRef (single target)
            ref = spec.get("targetRef", {})
            if ref.get("kind") == "Gateway" and ref.get("name") == gw_name:
                policies.setdefault(kind, []).append(item)
                continue
            # Check targetSelectors (multi-target)
            for sel in spec.get("targetSelectors", []):
                if (
                    sel.get("kind") == "Gateway"
                    and sel.get("group") == "gateway.networking.k8s.io"
                ):
                    policies.setdefault(kind, []).append(item)
                    break
    return policies


def _find_security_policies(route_name: str, route_ns: str) -> list[dict]:
    """Find SecurityPolicies targeting a specific HTTPRoute or its namespace."""
    args = ["kubectl", "get", "securitypolicies", "-n", route_ns, "-o", "json"]
    result = run(args, timeout=10, check=False)
    if result.returncode != 0 or not result.stdout:
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    matches = []
    for item in data.get("items", []):
        spec = item.get("spec", {})
        ref = spec.get("targetRef", {})
        if ref.get("kind") == "HTTPRoute" and ref.get("name") == route_name:
            matches.append(item)
            continue
        for sel in spec.get("targetSelectors", []):
            if sel.get("kind") == "HTTPRoute":
                matches.append(item)
                break
    return matches


def _extract_policy_details(policy: dict) -> list[tuple[str, str]]:
    """Extract interesting fields from a traffic policy spec as kv pairs."""
    spec = policy.get("spec", {})
    pairs: list[tuple[str, str]] = []

    # ClientTrafficPolicy fields
    timeout = spec.get("timeout", {})
    http_timeout = timeout.get("http", {})
    if http_timeout:
        for k, v in http_timeout.items():
            pairs.append((f"timeout.{k}", str(v)))

    conn = spec.get("connection", {})
    if conn:
        buf = conn.get("bufferLimit")
        if buf:
            pairs.append(("connection.bufferLimit", str(buf)))

    client_ip = spec.get("clientIPDetection", {})
    xff = client_ip.get("xForwardedFor", {})
    if xff:
        cidrs = xff.get("trustedCIDRs", [])
        if cidrs:
            pairs.append(("trustedCIDRs", ", ".join(cidrs)))

    tls = spec.get("tls", {})
    if tls:
        min_ver = tls.get("minVersion")
        if min_ver:
            pairs.append(("tls.minVersion", min_ver))
        alpn = tls.get("alpnProtocols", [])
        if alpn:
            pairs.append(("tls.alpn", ", ".join(alpn)))

    keepalive = spec.get("tcpKeepalive")
    if keepalive is not None:
        if isinstance(keepalive, dict) and keepalive:
            for k, v in keepalive.items():
                pairs.append((f"tcpKeepalive.{k}", str(v)))
        else:
            pairs.append(("tcpKeepalive", "enabled"))

    # BackendTrafficPolicy fields
    bt_timeout = spec.get("timeout", {}).get("http", {})
    if bt_timeout and not http_timeout:
        for k, v in bt_timeout.items():
            pairs.append((f"timeout.{k}", str(v)))

    retry = spec.get("retry", {})
    if retry:
        pairs.append(("retry.numRetries", str(retry.get("numRetries", "?"))))

    cb = spec.get("circuitBreaker", {})
    if cb:
        pairs.append(("circuitBreaker", "configured"))

    lb = spec.get("loadBalancer", {})
    if lb:
        lb_type = lb.get("type", "?")
        pairs.append(("loadBalancer", lb_type))

    return pairs


def _search_envoy_errors(hostnames: list[str], limit: int = 10) -> list[dict]:
    """Search envoy access logs for non-2xx responses to given hostnames."""
    result = run(
        [
            "kubectl",
            "logs",
            "-n",
            "network",
            "-l",
            "app.kubernetes.io/name=envoy",
            "--tail=2000",
            "--all-containers",
        ],
        timeout=30,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        return []

    errors: list[dict] = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        authority = entry.get(":authority", "")
        if not any(h in authority for h in hostnames):
            continue
        code = entry.get("response_code", 200)
        if isinstance(code, int) and code >= 400:
            errors.append(entry)

    return errors[-limit:]


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
    rt = _find_httproute(app, namespace)
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

    # Backend refs
    for rule in spec.get("rules", []):
        for ref in rule.get("backendRefs", []):
            kind = ref.get("kind", "Service")
            name = ref.get("name", "?")
            port = ref.get("port", "?")
            info(f"  backendRef: {kind}/{name}:{port}")

    # Parent status
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

    # Find parent Gateway and its policies
    gw_name = None
    gw_ns = None
    for parent in parents:
        gw_ref = parent.get("parentRef", {})
        gw_name = gw_ref.get("name")
        gw_ns = gw_ref.get("namespace", rt_ns)
        if gw_name:
            break

    if gw_name and gw_ns:
        # Gateway details
        section("GATEWAY")
        gw_args = ["kubectl", "get", "gateway", gw_name, "-n", gw_ns, "-o", "json"]
        result = run(gw_args, timeout=10, check=False)
        if result.returncode == 0 and result.stdout:
            try:
                gw_data = json.loads(result.stdout)
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
            except json.JSONDecodeError:
                info(f"Gateway: {gw_name} (failed to parse)")
        else:
            info(f"Gateway: {gw_name} (not found)")

        # Traffic policies
        section("POLICIES")
        policies = _find_policies_for_gateway(gw_name, gw_ns)
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
                details = _extract_policy_details(pol)
                if details:
                    kv(details, indent=2)
                else:
                    info("  (default settings)")

        # Security policies on the route
        sec_policies = _find_security_policies(rt_name, rt_ns)
        if sec_policies:
            for sp in sec_policies:
                sp_name = sp.get("metadata", {}).get("name", "?")
                info(f"SecurityPolicy: {sp_name}")
        # EnvoyProxy config
        try:
            gw_data_raw = run(
                ["kubectl", "get", "gateway", gw_name, "-n", gw_ns, "-o", "json"],
                timeout=10,
                check=False,
            )
            if gw_data_raw.returncode == 0:
                gw_obj = json.loads(gw_data_raw.stdout)
                gw_class_name = gw_obj.get("spec", {}).get("gatewayClassName", "")
                if gw_class_name:
                    gc_result = run(
                        [
                            "kubectl",
                            "get",
                            "gatewayclass",
                            gw_class_name,
                            "-o",
                            "json",
                        ],
                        timeout=10,
                        check=False,
                    )
                    if gc_result.returncode == 0:
                        gc_data = json.loads(gc_result.stdout)
                        params = gc_data.get("spec", {}).get("parametersRef", {})
                        ep_name = params.get("name", "")
                        ep_ns = params.get("namespace", gw_ns)
                        if ep_name:
                            ep_result = run(
                                [
                                    "kubectl",
                                    "get",
                                    "envoyproxy",
                                    ep_name,
                                    "-n",
                                    ep_ns,
                                    "-o",
                                    "json",
                                ],
                                timeout=10,
                                check=False,
                            )
                            if ep_result.returncode == 0:
                                ep_data = json.loads(ep_result.stdout)
                                ep_spec = ep_data.get("spec", {})
                                log_level = (
                                    ep_spec.get("logging", {})
                                    .get("level", {})
                                    .get("default", "?")
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
        except (json.JSONDecodeError, KeyError):
            pass

    # Envoy access log errors
    if hostnames:
        section("ENVOY ERRORS (recent)")
        error_entries = _search_envoy_errors(hostnames, limit=errors)
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
