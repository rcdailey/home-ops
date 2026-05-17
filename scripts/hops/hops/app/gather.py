"""Diagnose command internals: Flux status, workload, gateway, services.

Data-fetching functions called by the diagnose command. All functions
print output directly; there is no separate render layer.
"""

from __future__ import annotations

import click

from hops.app.events import compact_event_message
from hops.core.format import age_str, info, section, table, truncate
from hops.core.runner import kubectl_json, run, run_json


def diagnose_services(app_name: str, ns: str):
    """Show services matching an app (catches naming surprises)."""
    section("SERVICES")
    svc_data = kubectl_json("services", namespace=ns)
    rows = []
    for item in svc_data.get("items", []):
        meta = item.get("metadata", {})
        name = meta.get("name", "")
        labels = meta.get("labels", {})
        app_label = labels.get("app.kubernetes.io/name", "")
        if app_label != app_name and not name.startswith(app_name):
            continue
        spec = item.get("spec", {})
        stype = spec.get("type", "ClusterIP")
        ports = ", ".join(
            f"{p.get('name', '?')}:{p.get('port', '?')}" for p in spec.get("ports", [])
        )
        cluster_ip = spec.get("clusterIP", "")
        rows.append([name, stype, ports, cluster_ip])
    if rows:
        table(["SERVICE", "TYPE", "PORTS", "CLUSTER-IP"], rows)
    else:
        info(f"No services found for {app_name!r}")


def diagnose_externalsecrets(app_name: str, ns: str):
    """Show ExternalSecret sync status for an app."""
    es_data = kubectl_json("externalsecrets", namespace=ns)
    rows = []
    for item in es_data.get("items", []):
        meta = item.get("metadata", {})
        name = meta.get("name", "")
        if not name.startswith(app_name):
            continue
        conditions = item.get("status", {}).get("conditions", [])
        sync = "?"
        msg = ""
        for cond in conditions:
            if cond.get("type") == "Ready":
                sync = "Synced" if cond.get("status") == "True" else "Error"
                if sync == "Error":
                    msg = truncate(cond.get("message", ""), 100)
                break
        row = [name, sync]
        if msg:
            row.append(msg)
        rows.append(row)
    if rows:
        section("EXTERNALSECRETS")
        headers = ["NAME", "STATUS"]
        if any(len(r) > 2 for r in rows):
            headers.append("MESSAGE")
            for r in rows:
                if len(r) == 2:
                    r.append("")
        table(headers, rows)


def diagnose_workload(app_name: str, ns: str):
    """Diagnose a workload-based app: pods, restarts, logs."""
    section("PODS")
    pod_data = kubectl_json("pods", namespace=ns)
    pod_rows = []
    restart_details = []
    for item in pod_data.get("items", []):
        meta = item.get("metadata", {})
        name = meta.get("name", "")
        if not name.startswith(app_name):
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
        info(f"No pods found for {app_name!r}")

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
        if item["metadata"]["name"].startswith(app_name)
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
            click.echo(output)
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
                click.echo(output)
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
