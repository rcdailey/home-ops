#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "homeassistant-api",
#     "aiohttp",
# ]
# ///

"""Convenience wrapper for Home Assistant REST API calls."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

from homeassistant_api import Client
from homeassistant_api.errors import EndpointNotFoundError


def _env():
    domain = os.environ.get("SECRET_DOMAIN")
    token = os.environ.get("HASS_TOKEN")
    if not domain:
        print("Error: SECRET_DOMAIN is not set", file=sys.stderr)
        sys.exit(1)
    if not token:
        print("Error: HASS_TOKEN is not set", file=sys.stderr)
        sys.exit(1)
    return domain, token


def get_client() -> Client:
    domain, token = _env()
    return Client(f"https://ha.{domain}/api", token)


def _ws_error(msg: dict) -> str:
    """Extract error message from a failed WebSocket response."""
    return msg.get("error", {}).get("message", json.dumps(msg))


def _parse_time_arg(value: str, now: datetime) -> datetime:
    """Parse a time argument as hours-ago (number/Nh) or ISO timestamp."""
    try:
        hours = float(value.rstrip("h"))
        return now - timedelta(hours=hours)
    except ValueError:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def ws_call(handler):
    """Run an async handler with an authenticated WebSocket send function.

    The handler receives a single ``send`` coroutine that assigns message IDs
    automatically, sends the payload, and returns the response dict.
    """
    import aiohttp

    domain, token = _env()
    url = f"wss://ha.{domain}/api/websocket"
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url) as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": token})
            msg = await ws.receive_json()
            if msg["type"] != "auth_ok":
                print(json.dumps(msg), flush=True)
                return None

            msg_id = 0

            async def send(payload: dict) -> dict:
                nonlocal msg_id
                msg_id += 1
                payload["id"] = msg_id
                await ws.send_json(payload)
                return await ws.receive_json()

            return await handler(send)


DEFAULT_LIMIT = 20


# --- subcommands ---


def cmd_states(args: argparse.Namespace) -> None:
    with get_client() as client:
        if args.target and "." in args.target:
            # Full entity_id: single entity detail
            try:
                state = client.get_state(entity_id=args.target)
            except EndpointNotFoundError:
                print(f"Entity not found: {args.target}", file=sys.stderr)
                sys.exit(1)
            print(json.dumps(state.model_dump(), indent=2, default=str))
            return

        states = client.get_states()
        if args.target:
            # Filter by domain prefix
            filtered = [
                {
                    "entity_id": s.entity_id,
                    "state": s.state,
                    "name": s.attributes.get("friendly_name", ""),
                }
                for s in states
                if s.entity_id.startswith(f"{args.target}.")
            ]
        else:
            # Domain summary
            domains: dict[str, int] = {}
            for s in states:
                d = s.entity_id.split(".")[0]
                domains[d] = domains.get(d, 0) + 1
            result = sorted(
                [{"domain": d, "count": c} for d, c in domains.items()],
                key=lambda x: -x["count"],
            )
            print(json.dumps(result, indent=2))
            return

        limit = None if args.all else (args.n or DEFAULT_LIMIT)
        if limit:
            filtered = filtered[:limit]
        print(json.dumps(filtered, indent=2))


def cmd_template(args: argparse.Namespace) -> None:
    with get_client() as client:
        result = client.get_rendered_template(args.template)
        print(result)


def cmd_config(args: argparse.Namespace) -> None:
    with get_client() as client:
        if args.type == "automation":
            identifier = args.identifier
            if identifier.startswith("automation."):
                try:
                    state = client.get_state(entity_id=identifier)
                except EndpointNotFoundError:
                    print(
                        f"Entity not found: {identifier}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                identifier = state.attributes.get("id", "")
                if not identifier:
                    print(
                        f"Error: could not resolve automation id from {args.identifier}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
            resp = client.request(f"config/automation/config/{identifier}")
            print(json.dumps(resp, indent=2))
        elif args.type == "script":
            slug = args.identifier.removeprefix("script.")
            try:
                resp = client.request(f"config/script/config/{slug}")
            except EndpointNotFoundError:
                print(
                    f"Script config not found for slug: {slug}",
                    file=sys.stderr,
                )
                print(
                    "Hint: the config slug may differ from the entity_id. "
                    "Check GET /api/services filtered to 'script' domain.",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(json.dumps(resp, indent=2))


def cmd_attributes(args: argparse.Namespace) -> None:
    with get_client() as client:
        try:
            state = client.get_state(entity_id=args.entity_id)
        except EndpointNotFoundError:
            print(f"Entity not found: {args.entity_id}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(dict(state.attributes), indent=2, default=str))


def cmd_entity(args: argparse.Namespace) -> None:
    disabled_by = None if args.action == "enable" else "user"

    async def handler(send):
        msg = await send(
            {
                "type": "config/entity_registry/update",
                "entity_id": args.entity_id,
                "disabled_by": disabled_by,
            }
        )
        if msg.get("success"):
            entry = msg["result"]["entity_entry"]
            delay = msg["result"].get("reload_delay")
            status = "disabled" if entry.get("disabled_by") else "enabled"
            print(f"{entry['entity_id']}: {status}")
            if delay:
                print(f"Reload in {delay}s")
        else:
            print(json.dumps(msg, indent=2))

    asyncio.run(ws_call(handler))


def cmd_orient(args: argparse.Namespace) -> None:
    pattern = re.compile("|".join(re.escape(t) for t in args.terms), re.IGNORECASE)

    with get_client() as client:
        states = client.get_states()
        matches = [
            s
            for s in states
            if pattern.search(s.entity_id)
            or pattern.search(s.attributes.get("friendly_name", ""))
        ]
        entity_ids = {s.entity_id for s in matches}

        print("## Entities")
        for s in sorted(matches, key=lambda x: x.entity_id):
            name = s.attributes.get("friendly_name", "")
            print(f"  {s.entity_id}: {s.state}  ({name})")

        # Fetch and search automation configs
        automations = [s for s in states if s.entity_id.startswith("automation.")]
        print("\n## Automations")
        found = False
        for a in automations:
            config_id = a.attributes.get("id")
            if not config_id:
                continue
            try:
                config = client.request(f"config/automation/config/{config_id}")
            except Exception:
                continue
            config_str = json.dumps(config)
            if any(eid in config_str for eid in entity_ids) or pattern.search(
                config_str
            ):
                found = True
                alias = config.get("alias", a.entity_id)
                print(f"\n### {alias} ({a.entity_id}, state: {a.state})")
                print(json.dumps(config, indent=2))
        if not found:
            print("  (none found)")

        # Fetch and search script configs using service slugs (entity_id
        # doesn't always match the config slug in HA)
        try:
            all_services = client.request("services")
            script_slugs = [
                slug
                for svc in all_services
                if svc.get("domain") == "script"
                for slug in svc.get("services", {})
                if slug not in ("reload", "turn_on", "turn_off", "toggle")
            ]
        except Exception:
            script_slugs = []
        print("\n## Scripts")
        found = False
        for slug in script_slugs:
            try:
                config = client.request(f"config/script/config/{slug}")
            except Exception:
                continue
            config_str = json.dumps(config)
            if any(eid in config_str for eid in entity_ids) or pattern.search(
                config_str
            ):
                found = True
                alias = config.get("alias", slug)
                print(f"\n### {alias} (script.{slug})")
                print(json.dumps(config, indent=2))
        if not found:
            print("  (none found)")

    # Dashboard search via WebSocket (separate connection)
    async def search_dashboards(send):
        msg = await send({"type": "lovelace/dashboards/list"})
        dashboards = msg.get("result", [])

        configs = []
        msg = await send({"type": "lovelace/config"})
        configs.append(("default", msg.get("result", {})))
        for d in dashboards:
            url_path = d.get("url_path")
            if not url_path:
                continue
            msg = await send({"type": "lovelace/config", "url_path": url_path})
            result = msg.get("result")
            if isinstance(result, dict):
                configs.append((url_path, result))

        hits = []

        def search_cards(obj, path, dashboard_name, view_title):
            if isinstance(obj, dict):
                entity = obj.get("entity", "")
                if isinstance(entity, str) and (
                    entity in entity_ids or pattern.search(entity)
                ):
                    name = obj.get("name", "")
                    hits.append((dashboard_name, view_title, path, entity, name))
                for k, v in obj.items():
                    search_cards(v, f"{path}.{k}", dashboard_name, view_title)
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    search_cards(v, f"{path}[{i}]", dashboard_name, view_title)

        for dash_name, config in configs:
            for view in config.get("views", []):
                view_title = view.get("title", "(untitled)")
                search_cards(view, "view", dash_name, view_title)

        return hits

    print("\n## Dashboard Cards")
    hits = asyncio.run(ws_call(search_dashboards))
    if hits:
        for dash, view, path, entity, name in hits:
            label = f"{name} ({entity})" if name else entity
            print(f"  [{dash}] {view} > {label}")
    else:
        print("  (none found)")


def cmd_activity(args: argparse.Namespace) -> None:
    since = datetime.now(timezone.utc) - timedelta(hours=args.hours)

    with get_client() as client:
        entries = list(
            client.get_logbook_entries(
                filter_entities=args.entities,
                start_timestamp=since,
            )
        )

    if not entries:
        print("(no activity found)")
        return

    for e in entries:
        d = e.model_dump() if hasattr(e, "model_dump") else vars(e)
        ts = str(d.get("when", ""))
        # Extract just HH:MM:SS from the timestamp
        if "T" in ts:
            ts = ts.split("T")[1][:8]
        elif " " in ts:
            ts = ts.split(" ")[1][:8]
        name = d.get("name", d.get("entity_id", ""))
        state = d.get("state", "")
        message = d.get("message", "")
        parts = [ts, name]
        if state:
            parts.append(f"-> {state}")
        if message:
            parts.append(f"({message})")
        print("  ".join(parts))


def cmd_logs(args: argparse.Namespace) -> None:
    with get_client() as client:
        log_text = client.request("error_log")

    if not isinstance(log_text, str) or not log_text.strip():
        print("(no log entries)")
        return

    # Parse log lines: HA logs start with "YYYY-MM-DD HH:MM:SS.sss LEVEL"
    # Continuation lines (tracebacks, etc.) get attached to the previous entry.
    log_pattern = re.compile(
        r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\.\d+\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+"
    )
    entries: list[tuple[str, str, str]] = []
    for line in log_text.splitlines():
        m = log_pattern.match(line)
        if m:
            entries.append((m.group(1), m.group(2), line[m.end() :]))
        elif entries:
            ts, level, text = entries[-1]
            entries[-1] = (ts, level, text + "\n" + line)

    if not entries:
        print(log_text[:5000])
        return

    # Filter by severity
    severity_order = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    min_idx = severity_order.index(args.level.upper())
    allowed = set(severity_order[min_idx:])
    entries = [(ts, lv, txt) for ts, lv, txt in entries if lv in allowed]

    # Filter by grep pattern
    if args.grep:
        grep_re = re.compile(args.grep, re.IGNORECASE)
        entries = [(ts, lv, txt) for ts, lv, txt in entries if grep_re.search(txt)]

    # Apply tail limit
    if args.n and len(entries) > args.n:
        entries = entries[-args.n :]

    if not entries:
        print("(no matching entries)")
        return

    for ts, level, text in entries:
        # Compact timestamp to just time portion for readability
        time_part = ts.split(" ", 1)[1] if " " in ts else ts
        print(f"{time_part} {level:8s} {text}")


def cmd_repairs(args: argparse.Namespace) -> None:
    async def handler(send):
        if args.action == "dismiss":
            if not args.issue_id:
                print("Error: issue_id required for dismiss", file=sys.stderr)
                sys.exit(1)
            # issue_id format: "domain/issue_id" or just search for it
            parts = args.issue_id.split("/", 1)
            if len(parts) == 2:
                domain, issue_id = parts
            else:
                # Search for a matching issue
                msg = await send({"type": "repairs/list_issues"})
                issues = msg.get("result", {}).get("issues", [])
                matches = [i for i in issues if args.issue_id in i["issue_id"]]
                if not matches:
                    print(
                        f"No repair matching: {args.issue_id}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                if len(matches) > 1:
                    print(
                        f"Ambiguous, {len(matches)} matches:",
                        file=sys.stderr,
                    )
                    for m in matches:
                        print(
                            f"  {m['domain']}/{m['issue_id']}",
                            file=sys.stderr,
                        )
                    sys.exit(1)
                domain = matches[0]["domain"]
                issue_id = matches[0]["issue_id"]

            msg = await send(
                {
                    "type": "repairs/ignore_issue",
                    "domain": domain,
                    "issue_id": issue_id,
                    "ignore": True,
                }
            )
            if msg.get("success"):
                print(f"Dismissed: {domain}/{issue_id}")
            else:
                print(f"Failed: {_ws_error(msg)}", file=sys.stderr)
                sys.exit(1)
            return

        # Default: list
        msg = await send({"type": "repairs/list_issues"})
        issues = msg.get("result", {}).get("issues", [])
        issues = [i for i in issues if not i.get("ignored")]

        if not issues:
            print("(no repairs)")
            return

        for i in issues:
            sev = i["severity"].upper()
            domain = i["domain"]
            placeholders = i.get("translation_placeholders", {})
            key = i.get("translation_key", "")

            # Build a readable description from translation placeholders
            desc = _repair_description(key, placeholders, i["issue_id"])
            print(f"{sev:8s} {domain:20s} {desc}")

    asyncio.run(ws_call(handler))


def _repair_description(key: str, placeholders: dict, issue_id: str) -> str:
    """Build a human-readable description from repair metadata."""
    name = placeholders.get("name", "")
    entity = placeholders.get("entity_id", "")
    replacement = placeholders.get("replacement_entity_id", "")
    service = placeholders.get("service", "")

    if key == "service_not_found" and name and service:
        return f"{name}: unknown service {service}"
    if key == "deprecated_sensor" and entity and replacement:
        return f"Deprecated {entity} (replace with {replacement})"
    if key == "deprecated_sensor" and entity:
        return f"Deprecated {entity}"

    # Fallback: use whatever placeholders exist
    if name:
        return f"{name} ({key})"
    if entity:
        return f"{entity} ({key})"
    return issue_id


def cmd_area(args: argparse.Namespace) -> None:
    async def handler(send):
        if args.action == "list":
            msg = await send({"type": "config/area_registry/list"})
            areas = msg.get("result", [])
            for a in sorted(areas, key=lambda x: x["name"]):
                print(f"  {a['area_id']:25s} {a['name']}")
            return

        if args.action == "get":
            if not args.entity_id:
                print("Error: entity_id required for get", file=sys.stderr)
                sys.exit(1)
            msg = await send(
                {
                    "type": "config/entity_registry/get",
                    "entity_id": args.entity_id,
                }
            )
            if not msg.get("success"):
                print(f"Error: {_ws_error(msg)}", file=sys.stderr)
                sys.exit(1)
            entry = msg["result"]
            area = entry.get("area_id") or "(inherited from device)"
            device = entry.get("device_id", "")
            print(f"{entry['entity_id']}: area={area}, device={device}")
            return

        if args.action == "create":
            if not args.entity_id:
                print("Error: area name required for create", file=sys.stderr)
                sys.exit(1)
            area_name = args.entity_id  # positional reuse
            msg = await send({"type": "config/area_registry/create", "name": area_name})
            if msg.get("success"):
                area = msg["result"]
                print(f"Created: {area['area_id']} ({area['name']})")
            else:
                print(f"Failed: {_ws_error(msg)}", file=sys.stderr)
                sys.exit(1)
            return

        if args.action == "set":
            if not args.entity_id or not args.area:
                print(
                    "Error: entity_id and area required for set",
                    file=sys.stderr,
                )
                sys.exit(1)

            # Resolve area name/id
            msg = await send({"type": "config/area_registry/list"})
            areas = msg.get("result", [])
            area_map = {a["area_id"]: a for a in areas}
            name_map = {a["name"].lower(): a for a in areas}

            target = args.area
            if target in area_map:
                area_id = target
            elif target.lower() in name_map:
                area_id = name_map[target.lower()]["area_id"]
            else:
                print(f"Error: area not found: {target}", file=sys.stderr)
                print("Available areas:", file=sys.stderr)
                for a in sorted(areas, key=lambda x: x["name"]):
                    print(f"  {a['area_id']:25s} {a['name']}", file=sys.stderr)
                sys.exit(1)

            # Accept multiple entity IDs (comma-separated or multiple args)
            entity_ids = [
                eid.strip() for eid in args.entity_id.split(",") if eid.strip()
            ]

            for eid in entity_ids:
                msg = await send(
                    {
                        "type": "config/entity_registry/update",
                        "entity_id": eid,
                        "area_id": area_id,
                    }
                )
                if msg.get("success"):
                    entry = msg["result"]["entity_entry"]
                    new_area = entry.get("area_id", "(none)")
                    print(f"{eid}: area -> {new_area}")
                else:
                    print(f"{eid}: FAILED - {_ws_error(msg)}", file=sys.stderr)

    asyncio.run(ws_call(handler))


def cmd_history(args: argparse.Namespace) -> None:
    from urllib.parse import quote

    now = datetime.now(timezone.utc)
    start = _parse_time_arg(args.start, now)
    end = _parse_time_arg(args.end, now) if args.end else now

    entity_filter = ",".join(args.entities)
    path = (
        f"history/period/{quote(start.isoformat())}"
        f"?filter_entity_id={quote(entity_filter)}"
        f"&end_time={quote(end.isoformat())}"
        f"&minimal_response&no_attributes"
    )

    with get_client() as client:
        data = client.request(path)

    if not data:
        print("(no history)")
        return

    for series in data:
        if not series:
            continue

        # Identify entity from first entry
        entity_id = series[0].get("entity_id", "unknown")
        numeric = all(
            _is_numeric(e.get("state", ""))
            for e in series
            if e.get("state") not in ("unavailable", "unknown")
        )

        if args.json:
            print(json.dumps({"entity_id": entity_id, "states": series}, indent=2))
            continue

        print(f"--- {entity_id} ({len(series)} points) ---")

        if args.summary and numeric:
            values = [
                float(e["state"]) for e in series if _is_numeric(e.get("state", ""))
            ]
            if values:
                first_ts = series[0]["last_changed"]
                last_ts = series[-1]["last_changed"]
                resets = sum(
                    1 for i in range(1, len(values)) if values[i] < values[i - 1] * 0.5
                )
                print(f"  range:  {first_ts}  ->  {last_ts}")
                print(f"  first:  {values[0]}")
                print(f"  last:   {values[-1]}")
                print(f"  min:    {min(values)}")
                print(f"  max:    {max(values)}")
                print(f"  points: {len(values)}")
                if resets:
                    print(f"  resets: {resets}")
            continue

        # Default: print head/tail
        limit = args.n or 10
        head = series[:limit]
        tail = series[-limit:] if len(series) > limit * 2 else []
        skipped = len(series) - len(head) - len(tail)

        for entry in head:
            _print_history_entry(entry)
        if skipped > 0:
            print(f"  ... ({skipped} more)")
        for entry in tail:
            _print_history_entry(entry)


def _is_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def _print_history_entry(entry: dict) -> None:
    ts = entry.get("last_changed", "")
    # Show date+time but trim microseconds
    if "." in ts:
        ts = (
            ts[: ts.index(".")] + ts[ts.index("+") :]
            if "+" in ts
            else ts[: ts.index(".")]
        )
    state = entry.get("state", "")
    print(f"  {ts}  {state}")


def cmd_energy(args: argparse.Namespace) -> None:
    async def handler(send):
        if args.action == "validate":
            msg = await send({"type": "energy/validate"})
            result = msg.get("result", {})
            issues = []
            for section in (
                "energy_sources",
                "device_consumption",
                "device_consumption_water",
            ):
                for i, entry_issues in enumerate(result.get(section, [])):
                    for issue in entry_issues:
                        affected = issue.get("affected_entities", [])
                        entities = [e[0] for e in affected if e]
                        issues.append(
                            {
                                "section": section,
                                "index": i,
                                "type": issue["type"],
                                "entities": entities,
                            }
                        )
            if not issues:
                print("(valid)")
            else:
                for issue in issues:
                    ents = ", ".join(issue["entities"]) if issue["entities"] else ""
                    print(
                        f"{issue['section']}[{issue['index']}]: {issue['type']}  {ents}"
                    )
            return

        if args.action == "set":
            if not args.key or not args.value:
                print("Error: set requires KEY VALUE", file=sys.stderr)
                sys.exit(1)

            # Read current prefs
            msg = await send({"type": "energy/get_prefs"})
            if not msg.get("success"):
                print(f"Error: {_ws_error(msg)}", file=sys.stderr)
                sys.exit(1)
            prefs = msg["result"]

            key = args.key
            value = args.value

            if key.startswith("device."):
                # device.add <entity_id> or device.remove <entity_id>
                action = key.split(".", 1)[1]
                devices = prefs.get("device_consumption", [])

                if action == "add":
                    existing = {d["stat_consumption"] for d in devices}
                    if value in existing:
                        print(f"Already present: {value}")
                        return
                    devices.append({"stat_consumption": value})
                    prefs["device_consumption"] = devices
                    print(f"Adding: {value}")

                elif action == "remove":
                    before = len(devices)
                    devices = [d for d in devices if d["stat_consumption"] != value]
                    if len(devices) == before:
                        print(f"Not found: {value}", file=sys.stderr)
                        sys.exit(1)
                    prefs["device_consumption"] = devices
                    print(f"Removing: {value}")

                elif action == "replace":
                    # value format: "old_entity=new_entity"
                    if "=" not in value:
                        print(
                            "Error: replace format is old_entity=new_entity",
                            file=sys.stderr,
                        )
                        sys.exit(1)
                    old, new = value.split("=", 1)
                    found = False
                    for d in devices:
                        if d["stat_consumption"] == old:
                            d["stat_consumption"] = new
                            found = True
                            break
                    if not found:
                        print(f"Not found: {old}", file=sys.stderr)
                        sys.exit(1)
                    prefs["device_consumption"] = devices
                    print(f"Replacing: {old} -> {new}")

                else:
                    print(f"Unknown device action: {action}", file=sys.stderr)
                    sys.exit(1)

            else:
                print(f"Unknown key: {key}", file=sys.stderr)
                print(
                    "Supported keys: device.add, device.remove, device.replace",
                    file=sys.stderr,
                )
                sys.exit(1)

            # Save updated prefs
            save_payload = {"type": "energy/save_prefs"}
            save_payload.update(prefs)
            msg = await send(save_payload)
            if msg.get("success"):
                print("Saved.")
            else:
                print(f"Save failed: {_ws_error(msg)}", file=sys.stderr)
                sys.exit(1)
            return

        # Default: get (show current energy config)
        msg = await send({"type": "energy/get_prefs"})
        if not msg.get("success"):
            print(f"Error: {_ws_error(msg)}", file=sys.stderr)
            sys.exit(1)

        prefs = msg["result"]

        if args.json:
            print(json.dumps(prefs, indent=2))
            return

        # Readable output
        sources = prefs.get("energy_sources", [])
        devices = prefs.get("device_consumption", [])

        print("## Energy Sources")
        if not sources:
            print("  (none)")
        for s in sources:
            src_type = s.get("type", "unknown")
            if src_type == "grid":
                parts = [f"  grid: import={s.get('stat_energy_from', '(none)')}"]
                if s.get("stat_energy_to"):
                    parts.append(f"export={s['stat_energy_to']}")
                if s.get("entity_energy_price"):
                    parts.append(f"price={s['entity_energy_price']}")
                elif s.get("number_energy_price"):
                    parts.append(f"price=${s['number_energy_price']}")
                print(", ".join(parts))
            elif src_type == "solar":
                print(f"  solar: {s.get('stat_energy_from', '(none)')}")
            elif src_type == "battery":
                print(
                    f"  battery: from={s.get('stat_energy_from')}, to={s.get('stat_energy_to')}"
                )
            else:
                print(f"  {src_type}: {s.get('stat_energy_from', json.dumps(s))}")

        print("\n## Device Consumption")
        if not devices:
            print("  (none)")
        for d in devices:
            stat = d["stat_consumption"]
            name = d.get("name", "")
            label = f"{stat} ({name})" if name else stat
            print(f"  {label}")

        water = prefs.get("device_consumption_water", [])
        if water:
            print("\n## Water Consumption")
            for d in water:
                print(f"  {d['stat_consumption']}")

    asyncio.run(ws_call(handler))


def cmd_raw(args: argparse.Namespace) -> None:
    body = args.body
    if body == "-":
        body = sys.stdin.read()

    with get_client() as client:
        path = args.path.removeprefix("/api/")
        kwargs: dict = {}
        if body:
            kwargs["json"] = json.loads(body)

        method = args.method.upper()
        if method == "GET":
            resp = client.request(path)
        else:
            resp = client.request(path, method=method, **kwargs)

        if isinstance(resp, str):
            print(resp)
        else:
            print(json.dumps(resp, indent=2, default=str))


# --- CLI ---


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Home Assistant API wrapper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # states
    p = sub.add_parser("states", help="List entities (no arg: domain summary)")
    p.add_argument("target", nargs="?", help="Domain or entity_id")
    p.add_argument("-n", type=int, help=f"Limit results (default: {DEFAULT_LIMIT})")
    p.add_argument("--all", action="store_true", help="No limit")

    # template
    p = sub.add_parser("template", help="Render a Jinja2 template")
    p.add_argument("template", help="Jinja2 template string")

    # config
    p = sub.add_parser("config", help="Get automation/script config")
    p.add_argument("type", choices=["automation", "script"])
    p.add_argument("identifier", help="Entity ID, UUID, or slug")

    # attributes
    p = sub.add_parser("attributes", help="Show entity attributes")
    p.add_argument("entity_id")

    # entity
    p = sub.add_parser("entity", help="Enable/disable entity")
    p.add_argument("action", choices=["enable", "disable"])
    p.add_argument("entity_id")

    # orient
    p = sub.add_parser("orient", help="Discover related entities, automations, scripts")
    p.add_argument("terms", nargs="+", help="Search terms")

    # activity
    p = sub.add_parser("activity", help="Entity activity timeline")
    p.add_argument("entities", nargs="+", help="Entity IDs to query")
    p.add_argument("--hours", type=float, default=1, help="Lookback hours (default: 1)")

    # repairs
    p = sub.add_parser("repairs", help="List or dismiss HA repair issues")
    p.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "dismiss"],
        help="Action (default: list)",
    )
    p.add_argument(
        "issue_id",
        nargs="?",
        help="For dismiss: domain/issue_id or substring to match",
    )

    # logs
    p = sub.add_parser("logs", help="HA error log (parsed and filtered)")
    p.add_argument("grep", nargs="?", help="Regex pattern to filter log messages")
    p.add_argument(
        "-l",
        "--level",
        default="WARNING",
        help="Minimum severity: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: WARNING)",
    )
    p.add_argument(
        "-n",
        type=int,
        default=50,
        help="Show last N matching entries (default: 50)",
    )

    # history
    p = sub.add_parser("history", help="Entity state history over time")
    p.add_argument("entities", nargs="+", help="Entity IDs to query")
    p.add_argument(
        "--from",
        dest="start",
        default="24",
        help="Start: hours ago (e.g., 24, 1h) or ISO timestamp (default: 24h)",
    )
    p.add_argument(
        "--to",
        dest="end",
        default=None,
        help="End: hours ago or ISO timestamp (default: now)",
    )
    p.add_argument("-n", type=int, help="Head/tail entries per entity (default: 10)")
    p.add_argument(
        "--summary",
        action="store_true",
        help="Show min/max/first/last/resets instead of entries",
    )
    p.add_argument("--json", action="store_true", help="Raw JSON output")

    # area
    p = sub.add_parser("area", help="View or set entity area assignments")
    p.add_argument(
        "action",
        choices=["list", "get", "set", "create"],
        help="list/get/set/create areas and entity assignments",
    )
    p.add_argument(
        "entity_id",
        nargs="?",
        help="Entity ID (comma-separated for batch set) or area name (for create)",
    )
    p.add_argument("area", nargs="?", help="Area ID or name (for set)")

    # energy
    p = sub.add_parser("energy", help="Energy dashboard configuration")
    p.add_argument(
        "action",
        nargs="?",
        default="get",
        choices=["get", "validate", "set"],
        help="Action (default: get)",
    )
    p.add_argument(
        "key", nargs="?", help="For set: device.add, device.remove, device.replace"
    )
    p.add_argument("value", nargs="?", help="For set: entity_id or old=new (replace)")
    p.add_argument("--json", action="store_true", help="Raw JSON output")

    # raw
    p = sub.add_parser("raw", help="Direct API call")
    p.add_argument("method", help="HTTP method")
    p.add_argument("path", help="API path (e.g., /api/services)")
    p.add_argument("body", nargs="?", help="JSON body or - for stdin")

    args = parser.parse_args()
    {
        "states": cmd_states,
        "template": cmd_template,
        "config": cmd_config,
        "attributes": cmd_attributes,
        "entity": cmd_entity,
        "orient": cmd_orient,
        "activity": cmd_activity,
        "repairs": cmd_repairs,
        "logs": cmd_logs,
        "history": cmd_history,
        "area": cmd_area,
        "energy": cmd_energy,
        "raw": cmd_raw,
    }[args.command](args)


if __name__ == "__main__":
    main()
