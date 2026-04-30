"""Diagnose command internals: Flux status, workload, gateway, events, pod detail.

Extracted from app.py to keep the main module focused on CLI commands.
All functions are private helpers called only by `app.diagnose` and `app.pod`.
"""

from __future__ import annotations

from hops._format import age_str, info, section, table, truncate
from hops._runner import kubectl_json, run, run_json
from hops._workload import Workload


def find_gateway_namespace(app: str, namespace: str | None) -> str | None:
    """Find the namespace of a gateway-only app (Backend or Service + HTTPRoute)."""
    for resource in ("backends.gateway.envoyproxy.io", "services"):
        try:
            args = ["kubectl", "get", resource, app, "-o", "json"]
            if namespace:
                args.extend(["-n", namespace])
            else:
                args.append("--all-namespaces")
            data = run_json(args, timeout=10, quiet=True)
            ns = data.get("metadata", {}).get("namespace")
            if ns:
                return ns
        except SystemExit:
            continue
    return None


def diagnose_workload(wl: Workload, ns: str):
    """Diagnose a workload-based app: pods, restarts, logs."""
    section("PODS")
    pod_data = kubectl_json("pods", namespace=ns)
    pod_rows = []
    restart_details = []
    for item in pod_data.get("items", []):
        meta = item.get("metadata", {})
        name = meta.get("name", "")
        if not name.startswith(wl.name):
            continue
        spec = item.get("spec", {})
        status = item.get("status", {})
        phase = status.get("phase", "?")
        node = spec.get("nodeName", "?")
        age_val = age_str(meta.get("creationTimestamp"))

        restarts = 0
        for cs in status.get("containerStatuses", []):
            restarts += cs.get("restartCount", 0)
            if cs.get("restartCount", 0) > 0:
                last = cs.get("lastState", {}).get("terminated", {})
                if last:
                    restart_details.append(
                        {
                            "pod": name,
                            "container": cs.get("name", ""),
                            "exit_code": last.get("exitCode", "?"),
                            "reason": last.get("reason", "?"),
                            "finished": age_str(last.get("finishedAt")),
                        }
                    )

            waiting = cs.get("state", {}).get("waiting", {})
            if waiting:
                phase = waiting.get("reason", phase)

        pod_rows.append([name, node, phase, str(restarts), age_val])

    if pod_rows:
        table(["POD", "NODE", "STATUS", "RESTARTS", "AGE"], pod_rows)
    else:
        info(f"No pods found for {wl.name!r}")

    if restart_details:
        info("")
        info("Restart details:")
        for rd in restart_details:
            info(
                f"  {rd['pod']}/{rd['container']}: "
                f"exit={rd['exit_code']} reason={rd['reason']} "
                f"({rd['finished']} ago)"
            )

    # Recent logs
    section("LOGS (recent)")
    matching_pods = [
        item
        for item in pod_data.get("items", [])
        if item["metadata"]["name"].startswith(wl.name)
        and item.get("status", {}).get("phase") == "Running"
    ]
    if matching_pods:
        pod_name = matching_pods[0]["metadata"]["name"]
        result = run(
            [
                "kubectl",
                "logs",
                pod_name,
                "-n",
                ns,
                "--all-containers",
                "--since=1h",
                "--tail=20",
            ],
            timeout=15,
            check=False,
        )
        output = (result.stdout or "").strip()
        if output:
            print(output)
        else:
            info("(no recent logs)")
    else:
        info("(no running pods)")

    # Previous crash logs (auto-shown when restarts detected)
    if restart_details and matching_pods:
        section("LOGS (previous crash)")
        pod_name = matching_pods[0]["metadata"]["name"]
        shown = False
        for rd in restart_details:
            container_name = rd["container"]
            result = run(
                [
                    "kubectl",
                    "logs",
                    pod_name,
                    "-n",
                    ns,
                    "-c",
                    container_name,
                    "--previous",
                    "--tail=30",
                ],
                timeout=15,
                check=False,
            )
            output = (result.stdout or "").strip()
            if output:
                info(f"--- {container_name} (previous, last 30 lines) ---")
                print(output)
                shown = True
        if not shown:
            info("(no previous logs available)")


def diagnose_gateway(app: str, ns: str):
    """Diagnose a gateway-only app: Backend/Service + HTTPRoute status."""
    # Backend (Envoy Gateway)
    section("BACKEND")
    backend_found = False
    try:
        data = run_json(
            [
                "kubectl",
                "get",
                "backends.gateway.envoyproxy.io",
                app,
                "-n",
                ns,
                "-o",
                "json",
            ],
            timeout=10,
            quiet=True,
        )
        backend_found = True
        spec = data.get("spec", {})
        endpoints = spec.get("endpoints", [])
        tls = spec.get("tls", {})
        endpoint_strs = []
        for ep in endpoints:
            ip_spec = ep.get("ip", {})
            fqdn_spec = ep.get("fqdn", {})
            if ip_spec:
                endpoint_strs.append(
                    f"{ip_spec.get('address', '?')}:{ip_spec.get('port', '?')}"
                )
            elif fqdn_spec:
                endpoint_strs.append(
                    f"{fqdn_spec.get('hostname', '?')}:{fqdn_spec.get('port', '?')}"
                )
        info(f"Backend: {app}")
        info(f"  endpoints: {', '.join(endpoint_strs) if endpoint_strs else '(none)'}")
        if tls:
            skip = tls.get("insecureSkipVerify", False)
            info(f"  tls: insecureSkipVerify={skip}")
        _print_conditions(data)
    except SystemExit:
        pass

    # Service + Endpoints (headless external service pattern)
    if not backend_found:
        try:
            svc_data = run_json(
                ["kubectl", "get", "service", app, "-n", ns, "-o", "json"],
                timeout=10,
                quiet=True,
            )
            ports = svc_data.get("spec", {}).get("ports", [])
            port_strs = [f"{p.get('name', '?')}:{p.get('port', '?')}" for p in ports]
            info(f"Service: {app}")
            info(f"  ports: {', '.join(port_strs)}")

            try:
                ep_data = run_json(
                    ["kubectl", "get", "endpoints", app, "-n", ns, "-o", "json"],
                    timeout=10,
                    quiet=True,
                )
                subsets = ep_data.get("subsets", [])
                addrs = []
                for s in subsets:
                    for a in s.get("addresses", []):
                        ep_ports = [str(p.get("port", "?")) for p in s.get("ports", [])]
                        addrs.append(f"{a.get('ip', '?')}:{','.join(ep_ports)}")
                info(f"  endpoints: {', '.join(addrs) if addrs else '(none)'}")
            except SystemExit:
                info("  endpoints: (not found)")
        except SystemExit:
            info(f"No Backend or Service found for {app!r}")

    # HTTPRoute
    section("HTTPROUTE")
    try:
        route_data = run_json(
            ["kubectl", "get", "httproute", app, "-n", ns, "-o", "json"],
            timeout=10,
            quiet=True,
        )
        spec = route_data.get("spec", {})
        hostnames = spec.get("hostnames", [])
        info(f"HTTPRoute: {app}")
        info(f"  hostnames: {', '.join(hostnames) if hostnames else '(none)'}")

        for rule in spec.get("rules", []):
            refs = rule.get("backendRefs", [])
            for ref in refs:
                kind = ref.get("kind", "Service")
                name = ref.get("name", "?")
                port = ref.get("port", "?")
                info(f"  backendRef: {kind}/{name}:{port}")

        parents = route_data.get("status", {}).get("parents", [])
        for parent in parents:
            gw = parent.get("parentRef", {}).get("name", "?")
            info(f"  gateway: {gw}")
            for cond in parent.get("conditions", []):
                ctype = cond.get("type", "?")
                cstatus = cond.get("status", "?")
                reason = cond.get("reason", "")
                msg = cond.get("message", "")
                status_str = "yes" if cstatus == "True" else "no"
                detail = f" ({reason}: {truncate(msg, 80)})" if msg else ""
                info(f"    {ctype}: {status_str}{detail}")
    except SystemExit:
        info(f"HTTPRoute {app!r} not found in {ns}")


def _print_conditions(data: dict):
    """Print status conditions from a resource, if any."""
    conditions = data.get("status", {}).get("conditions", [])
    if not conditions:
        return
    for cond in conditions:
        ctype = cond.get("type", "?")
        cstatus = cond.get("status", "?")
        msg = cond.get("message", "")
        status_str = "yes" if cstatus == "True" else "no"
        detail = f": {truncate(msg, 80)}" if msg else ""
        info(f"  {ctype}: {status_str}{detail}")


def diagnose_events(app: str, ns: str):
    """Show non-Normal events filtered to an app name."""
    section(f"EVENTS (non-Normal, {ns})")
    events_args = [
        "kubectl",
        "get",
        "events",
        "-n",
        ns,
        "--sort-by=.lastTimestamp",
        "-o",
        "json",
    ]
    events_data = run_json(events_args, timeout=30)
    event_items = events_data.get("items", [])
    app_events = []
    for e in event_items:
        if e.get("type", "Normal") == "Normal":
            continue
        obj = e.get("involvedObject", {})
        obj_name = obj.get("name", "")
        if obj_name.startswith(app):
            app_events.append(e)

    # Deduplicate events with identical messages, keeping the most recent.
    # Strip trailing "Last Helm logs:" blocks before comparing (timestamps vary).
    def _dedup_key(msg: str) -> str:
        idx = msg.find("\n\nLast Helm logs:")
        return msg[:idx] if idx != -1 else msg

    seen_keys: dict[str, int] = {}
    deduped: list[dict] = []
    for e in reversed(app_events):
        key = _dedup_key(e.get("message", ""))
        if key not in seen_keys:
            seen_keys[key] = 0
            deduped.append(e)
        seen_keys[key] += 1
    deduped.reverse()
    deduped = deduped[-20:]

    if deduped:
        event_rows = []
        for e in deduped:
            reason = e.get("reason", "?")
            obj = e.get("involvedObject", {})
            obj_str = f"{obj.get('kind', '?')}/{obj.get('name', '?')}"
            msg = compact_event_message(e.get("message", ""))
            last_seen = age_str(e.get("lastTimestamp"))
            count = seen_keys.get(_dedup_key(e.get("message", "")), 1)
            count_str = f"x{count}" if count > 1 else ""
            event_rows.append([last_seen, reason, obj_str, count_str, msg])
        table(["AGE", "REASON", "OBJECT", "#", "MESSAGE"], event_rows)
    else:
        info("(none)")


def compact_event_message(msg: str) -> str:
    """Shorten verbose Helm template error chains to the actionable tail."""
    if "error calling include:" in msg or "error calling tpl:" in msg:
        for marker in ("error calling tpl:", "error calling include:"):
            idx = msg.rfind(marker)
            if idx != -1:
                tail = msg[idx:].strip()
                prefix = msg[:80].split(":")[0] if len(msg) > 200 else ""
                if prefix:
                    return f"{prefix}: ... {tail}"
                return tail
    return msg


def diagnose_flux(app: str, namespace: str):
    """Show Flux Kustomization and HelmRelease status for an app."""
    # Kustomization (check app namespace first, then flux-system)
    ks_found = False
    for ks_ns in [namespace, "flux-system"]:
        try:
            ks_data = run_json(
                ["kubectl", "get", "kustomization", app, "-n", ks_ns, "-o", "json"],
                timeout=10,
                quiet=True,
            )
            ks_status = _flux_ready_status(ks_data)
            info(f"Kustomization: {app}  {ks_status}")
            ks_found = True
            break
        except SystemExit:
            continue
    if not ks_found:
        info(f"Kustomization: {app}  (not found)")

    # HelmRelease
    try:
        hr_data = run_json(
            ["kubectl", "get", "helmrelease", app, "-n", namespace, "-o", "json"],
            timeout=10,
            quiet=True,
        )
        hr_status = _flux_ready_status(hr_data)
        info(f"HelmRelease:   {app}  {hr_status}")
    except SystemExit:
        info(f"HelmRelease:   {app}  (not found)")


def _flux_ready_status(data: dict) -> str:
    """Extract Ready condition from a Flux resource."""
    conditions = data.get("status", {}).get("conditions", [])
    for cond in conditions:
        if cond.get("type") == "Ready":
            status = "Ready" if cond.get("status") == "True" else "Not Ready"
            msg = cond.get("message", "")
            if msg and status == "Not Ready":
                return f"{status}: {compact_event_message(msg)}"
            return status
    return "Unknown"


# --- Pod detail (moved from app.py) ---
