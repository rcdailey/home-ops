"""Chart and release identity derived from HelmRelease status history."""

from __future__ import annotations

from hops.core.format import age_str


def chart_pairs(spec: dict, status: dict) -> list[tuple[str, str]]:
    """Chart and release identity for a HelmRelease.

    The deployed chart version lives in status.history, not in
    lastAppliedRevision (absent on HelmRelease), so reading it off the spec or
    the revision field leaves the caller parsing the Ready condition message
    for the version that is actually running. The previous entry comes along
    because the next question after "what is deployed" is almost always "what
    did it upgrade from".
    """
    history = status.get("history") or []
    current = history[0] if history else {}
    chart_ref = spec.get("chartRef", {})
    chart_spec = spec.get("chart", {}).get("spec", {})

    name = current.get("chartName") or chart_ref.get("name") or chart_spec.get("chart")
    version = current.get("chartVersion") or chart_spec.get("version") or "?"
    source = "chartRef" if chart_ref else "chart.spec"
    pairs = [("Chart", f"{name or '?'} {version} ({source})")]

    app_version = current.get("appVersion")
    if app_version and app_version != version:
        pairs.append(("App version", app_version))

    if current:
        release = f"v{current.get('version', '?')} {current.get('status', '?')}"
        pairs.append(
            ("Release", f"{release} ({age_str(current.get('lastDeployed'))} ago)")
        )

    previous = next((h for h in history[1:] if h.get("chartVersion") != version), None)
    if previous:
        prior = f"v{previous.get('version', '?')} {previous.get('status', '?')}"
        pairs.append(("Previous", f"{previous.get('chartVersion', '?')} ({prior})"))
    return pairs
