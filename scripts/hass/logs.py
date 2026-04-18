"""HA error log with severity filtering and regex grep."""

from __future__ import annotations

import re

import click

from hass._client import get_client

_SEVERITY = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
_LOG_LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\.\d+\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+"
)


@click.command()
@click.argument("grep_pattern", metavar="GREP", required=False)
@click.option(
    "-l",
    "--level",
    default="WARNING",
    type=click.Choice(_SEVERITY, case_sensitive=False),
    help="Minimum severity (default: WARNING)",
)
@click.option(
    "-n", "tail", type=int, default=50, help="Show last N entries (default: 50)"
)
def cli(grep_pattern: str | None, level: str, tail: int) -> None:
    """Parse /api/error_log, filter by severity, optional regex grep."""
    with get_client() as client:
        log_text = client.request("error_log")

    if not isinstance(log_text, str) or not log_text.strip():
        click.echo("(no log entries)")
        return

    entries: list[tuple[str, str, str]] = []
    for line in log_text.splitlines():
        m = _LOG_LINE.match(line)
        if m:
            entries.append((m.group(1), m.group(2), line[m.end() :]))
        elif entries:
            ts, lvl, text = entries[-1]
            entries[-1] = (ts, lvl, text + "\n" + line)

    if not entries:
        click.echo(log_text[:5000])
        return

    min_idx = _SEVERITY.index(level.upper())
    allowed = set(_SEVERITY[min_idx:])
    entries = [(ts, lv, txt) for ts, lv, txt in entries if lv in allowed]

    if grep_pattern:
        grep_re = re.compile(grep_pattern, re.IGNORECASE)
        entries = [(ts, lv, txt) for ts, lv, txt in entries if grep_re.search(txt)]

    if tail and len(entries) > tail:
        entries = entries[-tail:]

    if not entries:
        click.echo("(no matching entries)")
        return

    for ts, lvl, text in entries:
        time_part = ts.split(" ", 1)[1] if " " in ts else ts
        click.echo(f"{time_part} {lvl:8s} {text}")
