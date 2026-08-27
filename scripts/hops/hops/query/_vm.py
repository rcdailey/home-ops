"""VictoriaMetrics API helpers shared by metrics and alerts modules."""

from __future__ import annotations

import json
import sys
from typing import Any
from urllib.parse import urlencode

from hops.core.format import info
from hops.core.runner import tools_curl

VMSINGLE_URL = "http://vmsingle-victoria-metrics-k8s-stack.observability:8428"
VMALERT_URL = "http://vmalert-victoria-metrics-k8s-stack.observability:8080"
VMAGENT_URL = "http://vmagent-victoria-metrics-k8s-stack.observability:8429"

IGNORED_ALERTS = {"Watchdog", "InfoInhibitor"}
IGNORED_ALERT_PREFIXES = ("Unifi",)


def is_ignored_alert(alertname: str) -> bool:
    if alertname in IGNORED_ALERTS:
        return True
    return alertname.startswith(IGNORED_ALERT_PREFIXES)


def query_vm(endpoint: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    """Query VictoriaMetrics (VMSingle) and return parsed JSON."""
    url = f"{VMSINGLE_URL}{endpoint}"
    if params:
        url = f"{url}?{urlencode(params)}"
    return _parse(tools_curl(url, service_name="VictoriaMetrics"))


def query_vmalert(endpoint: str) -> dict[str, Any]:
    """Query VMAlert API and return parsed JSON."""
    return _parse(
        tools_curl(f"{VMALERT_URL}{endpoint}", service_name="VictoriaMetrics")
    )


def query_vmagent(endpoint: str) -> dict[str, Any]:
    """Query VMAgent API and return parsed JSON."""
    return _parse(tools_curl(f"{VMAGENT_URL}{endpoint}", service_name="VMAgent"))


def _parse(raw: str) -> dict[str, Any]:
    """Parse an API response, failing loudly on a backend-reported error.

    A rejected query still returns HTTP 200 with status=error, so callers that
    only read data.result cannot distinguish "no matches" from "query refused"
    and report a false negative.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        info("error: invalid JSON from VictoriaMetrics")
        sys.exit(1)
    if data.get("status") == "error":
        info(f"error: VictoriaMetrics rejected the query: {data.get('error', '')}")
        sys.exit(1)
    return data
