#!/usr/bin/env python3

"""Convenience wrapper for Home Assistant REST API calls."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys

from homeassistant_api import Client


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


async def ws_call(handler):
    """Run an async handler with an authenticated WebSocket connection."""
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
            return await handler(ws)


DEFAULT_LIMIT = 20


# --- subcommands ---


def cmd_states(args: argparse.Namespace) -> None:
    with get_client() as client:
        if args.target and "." in args.target:
            # Full entity_id: single entity detail
            state = client.get_state(entity_id=args.target)
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
                state = client.get_state(entity_id=identifier)
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
            resp = client.request(f"config/script/config/{slug}")
            print(json.dumps(resp, indent=2))


def cmd_attributes(args: argparse.Namespace) -> None:
    with get_client() as client:
        state = client.get_state(entity_id=args.entity_id)
        print(json.dumps(dict(state.attributes), indent=2, default=str))


def cmd_entity(args: argparse.Namespace) -> None:
    disabled_by = None if args.action == "enable" else "user"

    async def handler(ws):
        await ws.send_json(
            {
                "id": 1,
                "type": "config/entity_registry/update",
                "entity_id": args.entity_id,
                "disabled_by": disabled_by,
            }
        )
        msg = await ws.receive_json()
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

        # Find related automations
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

        # Find related scripts
        scripts = [s for s in states if s.entity_id.startswith("script.")]
        print("\n## Scripts")
        found = False
        for s in scripts:
            slug = s.entity_id.removeprefix("script.")
            try:
                config = client.request(f"config/script/config/{slug}")
            except Exception:
                continue
            config_str = json.dumps(config)
            if any(eid in config_str for eid in entity_ids) or pattern.search(
                config_str
            ):
                found = True
                alias = config.get("alias", s.entity_id)
                print(f"\n### {alias} ({s.entity_id})")
                print(json.dumps(config, indent=2))
        if not found:
            print("  (none found)")

        # Find related dashboard cards
        async def search_dashboards(ws):
            msg_id = 0

            async def ws_send(payload):
                nonlocal msg_id
                msg_id += 1
                payload["id"] = msg_id
                await ws.send_json(payload)
                return await ws.receive_json()

            # Get dashboard list
            msg = await ws_send({"type": "lovelace/dashboards/list"})
            dashboards = msg.get("result", [])

            # Collect all dashboard configs (default + named)
            configs = []
            msg = await ws_send({"type": "lovelace/config"})
            configs.append(("default", msg.get("result", {})))
            for d in dashboards:
                url_path = d.get("url_path")
                if not url_path:
                    continue
                msg = await ws_send({"type": "lovelace/config", "url_path": url_path})
                result = msg.get("result")
                if isinstance(result, dict):
                    configs.append((url_path, result))

            # Search cards recursively for matching entity_ids or terms
            hits = []

            def search(obj, path, dashboard_name, view_title):
                if isinstance(obj, dict):
                    entity = obj.get("entity", "")
                    if isinstance(entity, str) and (
                        entity in entity_ids or pattern.search(entity)
                    ):
                        name = obj.get("name", "")
                        hits.append((dashboard_name, view_title, path, entity, name))
                    for k, v in obj.items():
                        search(v, f"{path}.{k}", dashboard_name, view_title)
                elif isinstance(obj, list):
                    for i, v in enumerate(obj):
                        search(v, f"{path}[{i}]", dashboard_name, view_title)

            for dash_name, config in configs:
                for view in config.get("views", []):
                    view_title = view.get("title", "(untitled)")
                    search(view, "view", dash_name, view_title)

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
    from datetime import datetime, timedelta, timezone

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
        "raw": cmd_raw,
    }[args.command](args)


if __name__ == "__main__":
    main()
