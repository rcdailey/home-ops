"""VictoriaMetrics API helpers shared by metrics and alerts modules."""

from __future__ import annotations

import json
import sys
from typing import Any
from urllib.parse import urlencode

from hops._format import info
from hops._runner import tools_curl

VMSINGLE_URL = "http://vmsingle-victoria-metrics-k8s-stack.observability:8428"
VMALERT_URL = "http://vmalert-victoria-metrics-k8s-stack.observability:8080"

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
    raw = tools_curl(url, service_name="VictoriaMetrics")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        info("error: invalid JSON from VictoriaMetrics")
        sys.exit(1)


def query_vmalert(endpoint: str) -> dict[str, Any]:
    """Query VMAlert API and return parsed JSON."""
    raw = tools_curl(f"{VMALERT_URL}{endpoint}", service_name="VictoriaMetrics")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        info("error: invalid JSON from VictoriaMetrics")
        sys.exit(1)
