"""Event rendering for app diagnose and standalone event commands."""

from __future__ import annotations

from hops.core.format import age_str, info, section, table
from hops.core.runner import run_json


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
