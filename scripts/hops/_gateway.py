"""Gateway introspection helpers for debug route diagnostics."""

from __future__ import annotations

import json

from hops._runner import run


def find_httproute(name: str, namespace: str | None) -> dict | None:
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


def find_policies_for_gateway(gw_name: str, gw_ns: str) -> dict[str, list[dict]]:
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


def find_security_policies(route_name: str, route_ns: str) -> list[dict]:
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


def extract_policy_details(policy: dict) -> list[tuple[str, str]]:
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


def search_envoy_errors(hostnames: list[str], limit: int = 10) -> list[dict]:
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


def fetch_gateway(gw_name: str, gw_ns: str) -> dict | None:
    """Fetch a Gateway resource by name. Returns None if not found."""
    result = run(
        ["kubectl", "get", "gateway", gw_name, "-n", gw_ns, "-o", "json"],
        timeout=10,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def fetch_envoy_proxy(gw_data: dict, gw_ns: str) -> tuple[str, dict] | None:
    """Trace Gateway -> GatewayClass -> EnvoyProxy config.

    Returns (envoy_proxy_name, spec_dict) or None if the chain is broken.
    """
    gw_class_name = gw_data.get("spec", {}).get("gatewayClassName", "")
    if not gw_class_name:
        return None

    result = run(
        ["kubectl", "get", "gatewayclass", gw_class_name, "-o", "json"],
        timeout=10,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        return None
    try:
        gc_data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    params = gc_data.get("spec", {}).get("parametersRef", {})
    ep_name = params.get("name", "")
    ep_ns = params.get("namespace", gw_ns)
    if not ep_name:
        return None

    result = run(
        ["kubectl", "get", "envoyproxy", ep_name, "-n", ep_ns, "-o", "json"],
        timeout=10,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        return None
    try:
        ep_data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    return ep_name, ep_data.get("spec", {})
