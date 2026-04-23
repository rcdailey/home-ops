#!/usr/bin/env python3
"""CLI for inspecting QUI (qBittorrent management) via its REST API."""

import argparse
import json
import os
import sys
from urllib.parse import urljoin, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

SECRET_DOMAIN = os.environ.get("SECRET_DOMAIN", "")
BASE_URL = f"https://qui.{SECRET_DOMAIN}"
API_KEY = os.environ.get("QUI_API_KEY", "")


def _request(method: str, path: str, body: dict | None = None) -> dict | list | None:
    url = urljoin(BASE_URL, path)
    headers = {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except HTTPError as e:
        body_text = e.read().decode(errors="replace")
        print(f"HTTP {e.code}: {body_text}", file=sys.stderr)
        sys.exit(1)


def _json_out(data):
    json.dump(data, sys.stdout, indent=2)
    print()


def _check_env():
    if not SECRET_DOMAIN:
        print("Error: SECRET_DOMAIN env var is required", file=sys.stderr)
        sys.exit(1)
    if not API_KEY:
        print("Error: QUI_API_KEY env var is required", file=sys.stderr)
        sys.exit(1)


# -- Commands --


def cmd_instances(_args):
    """List configured qBittorrent instances."""
    _json_out(_request("GET", "/api/instances"))


def cmd_instance_info(args):
    """Get qBittorrent app info for an instance."""
    _json_out(_request("GET", f"/api/instances/{args.instance}/app-info"))


def cmd_instance_prefs(args):
    """Get qBittorrent preferences for an instance."""
    _json_out(_request("GET", f"/api/instances/{args.instance}/preferences"))


def cmd_transfer_info(args):
    """Get transfer stats for an instance."""
    _json_out(_request("GET", f"/api/instances/{args.instance}/transfer-info"))


def cmd_torrents(args):
    """List torrents for an instance."""
    params = {
        "limit": args.limit,
        "offset": args.offset,
        "sort": args.sort,
        "reverse": str(args.reverse).lower(),
    }
    if args.filter:
        params["filter"] = args.filter
    if args.category:
        params["category"] = args.category
    if args.tag:
        params["tag"] = args.tag
    if args.tracker:
        params["tracker"] = args.tracker
    qs = urlencode(params)
    _json_out(_request("GET", f"/api/instances/{args.instance}/torrents?{qs}"))


def cmd_torrent_trackers(args):
    """List trackers for a torrent."""
    _json_out(
        _request("GET", f"/api/instances/{args.instance}/torrents/{args.hash}/trackers")
    )


def cmd_torrent_props(args):
    """Get torrent properties."""
    _json_out(
        _request(
            "GET", f"/api/instances/{args.instance}/torrents/{args.hash}/properties"
        )
    )


def cmd_automations(args):
    """List automation rules for an instance."""
    _json_out(_request("GET", f"/api/instances/{args.instance}/automations"))


def cmd_automation_activity(args):
    """List recent automation activity."""
    _json_out(_request("GET", f"/api/instances/{args.instance}/automations/activity"))


def cmd_automation_dry_run(args):
    """Dry-run all automation rules."""
    body = {}
    if args.rule_id:
        body["ruleId"] = int(args.rule_id)
    _json_out(
        _request("POST", f"/api/instances/{args.instance}/automations/dry-run", body)
    )


def cmd_automation_apply(args):
    """Manually trigger automation rules to run now."""
    result = _request("POST", f"/api/instances/{args.instance}/automations/apply", {})
    _json_out(result)


def cmd_automation_update(args):
    """Update an automation rule from a JSON file."""
    with open(args.file) as f:
        body = json.load(f)
    result = _request(
        "PUT", f"/api/instances/{args.instance}/automations/{args.rule_id}", body
    )
    _json_out(result)


def cmd_categories(args):
    """List categories for an instance."""
    _json_out(_request("GET", f"/api/instances/{args.instance}/categories"))


def cmd_tags(args):
    """List tags for an instance."""
    _json_out(_request("GET", f"/api/instances/{args.instance}/tags"))


def cmd_trackers(args):
    """List active trackers across all torrents."""
    _json_out(_request("GET", f"/api/instances/{args.instance}/trackers"))


def cmd_cross_seed_settings(_args):
    """Get cross-seed settings."""
    _json_out(_request("GET", "/api/cross-seed/settings"))


def cmd_cross_seed_status(_args):
    """Get cross-seed scheduler status."""
    _json_out(_request("GET", "/api/cross-seed/status"))


def _add_instance_arg(parser):
    parser.add_argument("instance", help="Instance ID")


def main():
    _check_env()
    parser = argparse.ArgumentParser(description="QUI API client")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("instances", help="List instances").set_defaults(func=cmd_instances)

    p = sub.add_parser("instance-info", help="Instance app info")
    _add_instance_arg(p)
    p.set_defaults(func=cmd_instance_info)

    p = sub.add_parser("instance-prefs", help="Instance preferences")
    _add_instance_arg(p)
    p.set_defaults(func=cmd_instance_prefs)

    p = sub.add_parser("transfer-info", help="Transfer stats")
    _add_instance_arg(p)
    p.set_defaults(func=cmd_transfer_info)

    p = sub.add_parser("torrents", help="List torrents")
    _add_instance_arg(p)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--sort", default="added_on")
    p.add_argument("--reverse", action="store_true")
    p.add_argument("--filter", default=None, help="State filter")
    p.add_argument("--category", default=None)
    p.add_argument("--tag", default=None)
    p.add_argument("--tracker", default=None)
    p.set_defaults(func=cmd_torrents)

    p = sub.add_parser("torrent-trackers", help="Torrent trackers")
    _add_instance_arg(p)
    p.add_argument("hash", help="Torrent hash")
    p.set_defaults(func=cmd_torrent_trackers)

    p = sub.add_parser("torrent-props", help="Torrent properties")
    _add_instance_arg(p)
    p.add_argument("hash", help="Torrent hash")
    p.set_defaults(func=cmd_torrent_props)

    p = sub.add_parser("automations", help="List automation rules")
    _add_instance_arg(p)
    p.set_defaults(func=cmd_automations)

    p = sub.add_parser("automation-activity", help="Automation activity log")
    _add_instance_arg(p)
    p.set_defaults(func=cmd_automation_activity)

    p = sub.add_parser("automation-dry-run", help="Dry-run automations")
    _add_instance_arg(p)
    p.add_argument("--rule-id", default=None, help="Specific rule ID to dry-run")
    p.set_defaults(func=cmd_automation_dry_run)

    p = sub.add_parser("automation-apply", help="Trigger automations now")
    _add_instance_arg(p)
    p.set_defaults(func=cmd_automation_apply)

    p = sub.add_parser("automation-update", help="Update an automation rule")
    _add_instance_arg(p)
    p.add_argument("rule_id", help="Automation rule ID")
    p.add_argument("file", help="JSON file with updated rule body")
    p.set_defaults(func=cmd_automation_update)

    p = sub.add_parser("categories", help="List categories")
    _add_instance_arg(p)
    p.set_defaults(func=cmd_categories)

    p = sub.add_parser("tags", help="List tags")
    _add_instance_arg(p)
    p.set_defaults(func=cmd_tags)

    p = sub.add_parser("trackers", help="List active trackers")
    _add_instance_arg(p)
    p.set_defaults(func=cmd_trackers)

    sub.add_parser("cross-seed-settings", help="Cross-seed settings").set_defaults(
        func=cmd_cross_seed_settings
    )
    sub.add_parser("cross-seed-status", help="Cross-seed status").set_defaults(
        func=cmd_cross_seed_status
    )

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
