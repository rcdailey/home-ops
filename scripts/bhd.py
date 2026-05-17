#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["click", "httpx", "humanize"]
# ///
"""CLI for querying the BeyondHD tracker API."""

import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import click
import httpx
import humanize

API_KEY = os.environ.get("BHD_API_KEY", "")
RSS_KEY = os.environ.get("BHD_RSS_KEY", "")
BASE_URL = "https://beyond-hd.me/api/torrents"

SCRIPT_DIR = Path(__file__).resolve().parent
QUI_SCRIPT = SCRIPT_DIR / "qui.py"

CACHE_DIR = Path(tempfile.gettempdir()) / "bhd-cache"
CACHE_TTL = 600  # 10 minutes


# -- Cache --


def _cache_key(body: dict) -> str:
    normalized = {k: v for k, v in sorted(body.items()) if k != "rsskey"}
    return hashlib.sha256(json.dumps(normalized).encode()).hexdigest()[:16]


def _cache_get(key: str) -> dict | None:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > CACHE_TTL:
        path.unlink(missing_ok=True)
        return None
    return json.loads(path.read_text())


def _cache_put(key: str, data: dict):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(json.dumps(data))


# -- API --


def _request(body: dict, use_cache: bool = False) -> dict:
    if use_cache:
        key = _cache_key(body)
        cached = _cache_get(key)
        if cached is not None:
            return cached

    r = httpx.post(
        f"{BASE_URL}/{API_KEY}",
        json=body,
        headers={"User-Agent": "bhd-cli/1.0"},
        timeout=30,
    )
    r.raise_for_status()
    result = r.json()

    if use_cache and result.get("status_code") == 1:
        _cache_put(key, result)

    return result


# -- Helpers --


PROMO_FLAGS = [
    "freeleech",
    "refund",
    "rescue",
    "rewind",
    "promo25",
    "promo50",
    "promo75",
]

PROMO_WEIGHTS = {
    "freeleech": 1.0,
    "refund": 1.0,
    "rescue": 0.9,
    "rewind": 0.9,
    "promo25": 0.75,
    "promo50": 0.5,
    "promo75": 0.25,
}


def _promo_label(t: dict) -> str:
    for flag in PROMO_FLAGS:
        if t.get(flag):
            return {
                "freeleech": "FL",
                "refund": "refund",
                "rescue": "rescue",
                "rewind": "rewind",
                "promo25": "25%",
                "promo50": "50%",
                "promo75": "75%",
            }.get(flag, "")
    if t.get("limited"):
        return "limited"
    return ""


def _promo_weight(t: dict) -> float:
    for flag, weight in PROMO_WEIGHTS.items():
        if t.get(flag):
            return weight
    return 0.0


def _completion_rate(t: dict) -> float:
    """Daily completion rate (completions / age_days)."""
    completions = t.get("times_completed", 0)
    created = t.get("created_at", "")
    if not created:
        return float(completions)
    try:
        created_dt = datetime.strptime(created, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        age_days = max((datetime.now(timezone.utc) - created_dt).days, 1)
    except (ValueError, TypeError):
        return float(completions)
    return completions / age_days


def _score(t: dict) -> float:
    """Score for set-and-forget ratio building.

    (completions/day) / (seeders+1)^2  *  promo_weight  *  log2(size_gib+1)

    - Daily completion rate normalizes for torrent age; a recent torrent
      with 10 snatches in a week scores far above a 4-year-old torrent
      with 22 lifetime snatches.
    - Squaring (seeders+1) heavily penalizes crowded swarms where your share
      of any future leecher is negligible.
    - log2(size+1) rewards larger torrents: leechers stay connected longer,
      producing more sustained upload per snatch.
    """
    rate = _completion_rate(t)
    seeders = t.get("seeders", 0)
    size_gib = max(t.get("size", 0) / (1024**3), 0.01)
    demand = rate / (seeders + 1) ** 2
    return demand * _promo_weight(t) * math.log2(size_gib + 1)


def _size(n: int) -> str:
    return humanize.naturalsize(n, binary=True, format="%.1f")


def _collect_promo_results(
    promo_types: list[str],
    categories: str | None,
    search: str | None,
    limit: int,
    max_pages: int,
) -> list[dict]:
    """Fetch torrents across promo types with caching, rate limit handling,
    and early termination.

    Strategy:
    - Promo types ordered by value (free first, partial discounts last).
    - Sorted by times_completed desc to surface proven-demand torrents
      (scoring penalizes high seeders client-side).
    - Stop collecting once we have 2x the requested limit (scoring headroom).
    - 2s delay between API calls; abort all on rate limit.
    - Responses cached for 10 minutes so preview-then-grab doesn't double-hit.
    """
    target = limit * 2
    seen_ids: set[int] = set()
    all_results: list[dict] = []
    rate_limited = False
    api_calls = 0

    for flag in promo_types:
        if rate_limited or len(all_results) >= target:
            break

        body: dict = {
            "action": "search",
            "sort": "times_completed",
            "order": "desc",
            flag: 1,
            "alive": 1,
        }
        if RSS_KEY:
            body["rsskey"] = RSS_KEY
        if categories:
            body["categories"] = [int(c) for c in categories.split(",")]
        if search:
            body["search"] = search

        for page in range(1, max_pages + 1):
            if rate_limited or len(all_results) >= target:
                break

            body["page"] = page
            if api_calls > 0:
                time.sleep(2)

            result = _request(body, use_cache=True)
            api_calls += 1

            if result.get("status_code") != 1:
                msg = result.get("status_message", "")
                if "rate limit" in msg.lower():
                    click.echo(
                        "Rate limited, using results collected so far.", err=True
                    )
                    rate_limited = True
                    break
                click.echo(f"API error ({flag} p{page}): {msg}", err=True)
                continue

            page_results = result.get("results", [])

            new_count = 0
            for t in page_results:
                if t["id"] not in seen_ids:
                    seen_ids.add(t["id"])
                    all_results.append(t)
                    new_count += 1

            if new_count == 0 or len(page_results) < 100:
                break

    return all_results


# -- CLI --


@click.group()
def cli():
    """BeyondHD API client."""
    if not API_KEY:
        click.echo("Error: BHD_API_KEY env var is required", err=True)
        raise SystemExit(1)


@cli.command()
@click.argument("search", required=False, default=None)
@click.option("--page", type=int, default=None)
@click.option(
    "--sort",
    default=None,
    type=click.Choice(
        [
            "bumped_at",
            "created_at",
            "seeders",
            "leechers",
            "times_completed",
            "size",
            "name",
            "imdb_rating",
            "tmdb_rating",
            "bhd_rating",
        ]
    ),
)
@click.option("--order", default=None, type=click.Choice(["asc", "desc"]))
@click.option("--categories", default=None, help="Comma-separated: 1=Movies, 2=TV")
@click.option("--alive", is_flag=True, help="At least 1 seeder")
@click.option("--dying", is_flag=True, help="Less than 3 seeders")
@click.option("--dead", is_flag=True, help="No seeders")
@click.option("--freeleech", is_flag=True)
@click.option("--promo25", is_flag=True)
@click.option("--promo50", is_flag=True)
@click.option("--promo75", is_flag=True)
@click.option("--rescue", is_flag=True)
@click.option("--refund", is_flag=True)
@click.option("--rewind", is_flag=True)
@click.option("--imdb-id", default=None)
@click.option("--tmdb-id", default=None)
@click.option("--pack", is_flag=True, help="TV packs only")
def search(search, **kwargs):
    """Search torrents and output raw JSON."""
    body: dict = {"action": "search"}
    if RSS_KEY:
        body["rsskey"] = RSS_KEY
    if search:
        body["search"] = search

    flag_map = {
        "page": "page",
        "sort": "sort",
        "order": "order",
        "imdb_id": "imdb_id",
        "tmdb_id": "tmdb_id",
    }
    for opt, key in flag_map.items():
        if kwargs.get(opt):
            body[key] = kwargs[opt]
    if kwargs.get("categories"):
        body["categories"] = [int(c) for c in kwargs["categories"].split(",")]
    for flag in [
        "alive",
        "dying",
        "dead",
        "freeleech",
        "promo25",
        "promo50",
        "promo75",
        "rescue",
        "refund",
        "rewind",
        "pack",
    ]:
        if kwargs.get(flag):
            body[flag] = 1

    result = _request(body)
    if result.get("status_code") != 1:
        click.echo(f"API error: {result.get('status_message', 'unknown')}", err=True)
        raise SystemExit(1)
    click.echo(json.dumps(result, indent=2))


@cli.command("ratio-picks")
@click.argument("search", required=False, default=None)
@click.option("--categories", default=None, help="1=Movies, 2=TV")
@click.option("--freeleech", is_flag=True)
@click.option("--promo25", is_flag=True)
@click.option("--promo50", is_flag=True)
@click.option("--promo75", is_flag=True)
@click.option("--rescue", is_flag=True)
@click.option("--refund", is_flag=True)
@click.option("--rewind", is_flag=True)
@click.option(
    "--any-promo", is_flag=True, help="Search high-value promo types (excludes promo75)"
)
@click.option("--max-size", type=float, default=None, help="Max torrent size in GiB")
@click.option(
    "--max-seeders",
    type=int,
    default=None,
    help="Exclude torrents with more than N seeders",
)
@click.option("--limit", type=int, default=20, help="Number of results")
@click.option("--pages", type=int, default=1, help="API pages per promo type")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
@click.option("-v", "--verbose", is_flag=True, help="Show scoring breakdown")
def ratio_picks(
    search,
    categories,
    freeleech,
    promo25,
    promo50,
    promo75,
    rescue,
    refund,
    rewind,
    any_promo,
    max_size,
    max_seeders,
    limit,
    pages,
    as_json,
    verbose,
):
    """Find best torrents for ratio building."""
    # Ordered by value; --any-promo skips promo75 (use --promo75 explicitly)
    promo_types = []
    flag_opts = {
        "freeleech": freeleech,
        "refund": refund,
        "rescue": rescue,
        "rewind": rewind,
        "promo50": promo50,
        "promo25": promo25,
    }
    for flag, enabled in flag_opts.items():
        if enabled or any_promo:
            promo_types.append(flag)
    if promo75:
        promo_types.append("promo75")
    if not promo_types:
        promo_types = ["freeleech"]

    all_results = _collect_promo_results(promo_types, categories, search, limit, pages)
    all_results.sort(key=_score, reverse=True)

    if max_size:
        all_results = [
            t for t in all_results if t.get("size", 0) / (1024**3) <= max_size
        ]
    if max_seeders is not None:
        all_results = [t for t in all_results if t.get("seeders", 0) <= max_seeders]

    results = all_results[:limit]

    if as_json:
        click.echo(json.dumps(results, indent=2))
        return

    if not results:
        click.echo("No ratio-building candidates found.")
        return

    if verbose:
        click.echo(
            f"{'#':>3}  {'Promo':6}  {'S':>4}  {'L':>4}  {'Comp':>5}  "
            f"{'C/day':>5}  {'Size':>10}  {'Demand':>6}  "
            f"{'Score':>7}  Name"
        )
        click.echo("-" * 120)
        for i, t in enumerate(results, 1):
            seeders = t.get("seeders", 0)
            leechers = t.get("leechers", 0)
            completions = t.get("times_completed", 0)
            rate = _completion_rate(t)
            click.echo(
                f"{i:3}  {_promo_label(t):6}  {seeders:4}  {leechers:4}  "
                f"{completions:5}  {rate:5.2f}  "
                f"{_size(t.get('size', 0)):>10}  "
                f"{rate / (seeders + 1) ** 2:6.3f}  "
                f"{_score(t):7.4f}  "
                f"{t.get('name', '?')[:48]}"
            )
    else:
        click.echo(
            f"{'#':>3}  {'Promo':6}  {'S':>4}  {'L':>4}  {'Comp':>5}  "
            f"{'C/day':>5}  {'Size':>10}  {'Score':>7}  Name"
        )
        click.echo("-" * 110)
        for i, t in enumerate(results, 1):
            click.echo(
                f"{i:3}  {_promo_label(t):6}  {t.get('seeders', 0):4}  "
                f"{t.get('leechers', 0):4}  {t.get('times_completed', 0):5}  "
                f"{_completion_rate(t):5.2f}  "
                f"{_size(t.get('size', 0)):>10}  "
                f"{_score(t):7.4f}  {t.get('name', '?')[:48]}"
            )

    click.echo()
    total = sum(t.get("size", 0) for t in results)
    click.echo(f"Total download: {_size(total)}")


@cli.command()
@click.option(
    "--ids", default=None, help="Filter to specific BHD torrent IDs (comma-separated)"
)
@click.option("--url", default=None, help="Single BHD download URL")
@click.option("--instance", default="1", help="QUI instance ID")
@click.option("--category", default="manual")
@click.option("--tags", default="bhd-ratio", help="Comma-separated tags")
@click.option("--limit", type=int, default=None, help="Grab only first N torrents")
@click.option("--paused", is_flag=True)
def grab(ids, url, instance, category, tags, limit, paused):
    """Download from BHD and add to qBittorrent via QUI."""
    if not RSS_KEY:
        click.echo("Error: BHD_RSS_KEY env var is required for grab", err=True)
        raise SystemExit(1)

    torrents = []
    if url:
        torrents.append({"name": "manual", "download_url": url, "size": 0})
    elif not sys.stdin.isatty():
        data = json.load(sys.stdin)
        if isinstance(data, dict) and "results" in data:
            data = data["results"]
        torrents = data
    else:
        click.echo(
            "Provide torrent data via stdin (pipe from ratio-picks --json) "
            "or use --url",
            err=True,
        )
        raise SystemExit(1)

    if ids:
        wanted = {int(x) for x in ids.split(",")}
        torrents = [t for t in torrents if t.get("id") in wanted]

    if limit is not None:
        torrents = torrents[:limit]

    if not torrents:
        click.echo("No torrents to grab.", err=True)
        raise SystemExit(1)

    failures = 0
    for torrent in torrents:
        download_url = torrent.get("download_url")
        if not download_url:
            click.echo(
                f"Skipping {torrent.get('name', '?')}: no download_url", err=True
            )
            continue

        name = torrent.get("name", "unknown")
        click.echo(f"Downloading: {name}")
        if torrent.get("size"):
            click.echo(
                f"  Size: {_size(torrent['size'])}  "
                f"Promo: {_promo_label(torrent) or 'none'}  "
                f"S:{torrent.get('seeders', '?')} "
                f"L:{torrent.get('leechers', '?')}"
            )

        r = httpx.get(download_url, headers={"User-Agent": "bhd-cli/1.0"}, timeout=30)
        r.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".torrent", delete=False) as tmp:
            tmp.write(r.content)
            tmp_path = tmp.name

        try:
            cmd = [
                "uv",
                "run",
                str(QUI_SCRIPT),
                "add-torrent",
                instance,
                "--file",
                tmp_path,
            ]
            if category:
                cmd += ["--category", category]
            if tags:
                cmd += ["--tags", tags]
            if paused:
                cmd.append("--paused")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                click.echo(result.stderr, err=True, nl=False)
                failures += 1
            else:
                click.echo(result.stdout, nl=False)
        finally:
            os.unlink(tmp_path)

        click.echo()

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
