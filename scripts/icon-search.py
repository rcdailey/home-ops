#!/usr/bin/env python3

"""Search for dashboard icons from homarr-labs/dashboard-icons.

Examples:
  %(prog)s plex                     # Search for 'plex' icons
  %(prog)s plex radarr sonarr       # Search multiple patterns
  %(prog)s "home assistant"         # Search with spaces
  %(prog)s arr                      # Find all *arr apps
  %(prog)s --format svg plex        # Show only SVG icons
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

TREE_URL = "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons@main/tree.json"
CDN_BASE = "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons"
CACHE_FILE = Path("/tmp/dashboard-icons-tree.json")
CACHE_MAX_AGE = 86400  # 24 hours


def fetch_tree() -> dict:
    """Fetch icon tree from CDN with local caching."""
    if CACHE_FILE.exists():
        age = CACHE_FILE.stat().st_mtime
        import time

        if time.time() - age < CACHE_MAX_AGE:
            return json.loads(CACHE_FILE.read_text())

    with urllib.request.urlopen(TREE_URL, timeout=10) as resp:
        data = json.loads(resp.read().decode())

    CACHE_FILE.write_text(json.dumps(data))
    return data


def search_icons(tree: dict, pattern: str, fmt: str | None = None) -> list[dict]:
    """Search icons matching pattern."""
    regex = re.compile(re.escape(pattern).replace(r"\ ", ".*"), re.IGNORECASE)
    results = []

    formats = [fmt] if fmt else ["svg", "png", "webp"]

    for icon_fmt in formats:
        if icon_fmt not in tree:
            continue
        for icon in tree[icon_fmt]:
            name = icon.rsplit(".", 1)[0]  # Remove extension
            if regex.search(name):
                results.append(
                    {
                        "name": name,
                        "format": icon_fmt,
                        "file": icon,
                        "url": f"{CDN_BASE}/{icon_fmt}/{icon}",
                    }
                )

    # Deduplicate by name, preferring svg > png > webp
    seen = {}
    format_priority = {"svg": 0, "png": 1, "webp": 2}
    for r in sorted(results, key=lambda x: format_priority.get(x["format"], 99)):
        if r["name"] not in seen:
            seen[r["name"]] = r

    return list(seen.values())


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "patterns", nargs="+", help="Search pattern(s) (case-insensitive)"
    )
    parser.add_argument(
        "--format", "-f", choices=["svg", "png", "webp"], help="Filter by format"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--url", action="store_true", help="Show CDN URLs instead of names"
    )
    args = parser.parse_args()

    try:
        tree = fetch_tree()
    except Exception as e:
        print(f"Error fetching icon tree: {e}", file=sys.stderr)
        sys.exit(1)

    all_results = {}
    any_found = False

    for pattern in args.patterns:
        results = search_icons(tree, pattern, args.format)
        all_results[pattern] = results
        if results:
            any_found = True

    if args.json:
        print(json.dumps(all_results, indent=2))
    else:
        for pattern, results in all_results.items():
            if len(args.patterns) > 1:
                print(f"### {pattern}")
            if not results:
                print("  (no matches)", file=sys.stderr)
            elif args.url:
                for r in results:
                    print(r["url"])
            else:
                for r in results:
                    print(f"  {r['name']:<38} ({r['format']})")
            if len(args.patterns) > 1:
                print()

    if not any_found:
        sys.exit(1)


if __name__ == "__main__":
    main()
