"""Event rendering for app diagnose and standalone event commands."""

from __future__ import annotations

from hops.core.format import age_str, info, section, table, truncate
from hops.core.runner import run_json


def diagnose_events(app: str, ns: str):
    """Show actionable non-Normal events filtered to an app name."""
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
    object_cache: dict[tuple[str, str], dict | None] = {}
    for e in event_items:
        if e.get("type", "Normal") == "Normal":
            continue
        obj = e.get("involvedObject", {})
        obj_name = obj.get("name", "")
        if app.lower() not in obj_name.lower():
            continue
        if _healthy_or_gone(obj, ns, object_cache):
            continue
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


def _healthy_or_gone(
    obj: dict, namespace: str, cache: dict[tuple[str, str], dict | None]
) -> bool:
    """Suppress historical events for deleted or currently healthy objects."""
    kind = obj.get("kind", "")
    name = obj.get("name", "")
    if not kind or not name:
        return False
    key = (kind, name)
    if key not in cache:
        try:
            cache[key] = run_json(
                ["kubectl", "get", f"{kind}/{name}", "-n", namespace, "-o", "json"],
                timeout=10,
                quiet=True,
            )
        except SystemExit:
            cache[key] = None
    resource = cache[key]
    if resource is None:
        return True
    if obj.get("uid") and obj.get("uid") != resource.get("metadata", {}).get("uid"):
        return True

    status = resource.get("status", {})
    if kind == "Pod":
        if status.get("phase") not in {"Running", "Succeeded"}:
            return False
        statuses = [
            *status.get("initContainerStatuses", []),
            *status.get("containerStatuses", []),
        ]
        return all(item.get("ready", True) for item in statuses)
    return any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in status.get("conditions", [])
    )


def compact_event_message(msg: str) -> str:
    """Shorten verbose Helm template error chains to the actionable tail."""
    msg = " ".join(msg.split())
    if "error calling include:" in msg or "error calling tpl:" in msg:
        for marker in ("error calling tpl:", "error calling include:"):
            idx = msg.rfind(marker)
            if idx != -1:
                tail = msg[idx:].strip()
                prefix = msg[:80].split(":")[0] if len(msg) > 200 else ""
                if prefix:
                    return truncate(f"{prefix}: ... {tail}")
                return truncate(tail)
    return truncate(msg)
