"""HA error log with severity filtering, regex grep, and duplicate squashing."""

from __future__ import annotations

import re
from collections import OrderedDict

import click

from hass._client import get_client

_SEVERITY = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
_LOG_LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\.\d+\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+"
)


def _time_part(ts: str) -> str:
    return ts.split(" ", 1)[1] if " " in ts else ts


def _body_summary(text: str) -> str:
    """Headline (first line) plus last non-empty line for traceback exceptions."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return text
    head = lines[0]
    if len(lines) == 1:
        return head
    tail = lines[-1].strip()
    if tail == head.strip():
        return head
    return f"{head}  |  {tail}"


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
@click.option(
    "--full",
    is_flag=True,
    help="Disable duplicate squashing; print every entry body in full",
)
def cli(grep_pattern: str | None, level: str, tail: int, full: bool) -> None:
    """Parse /api/error_log, filter by severity, optional regex grep.

    By default, entries with identical bodies (common for recurring tracebacks)
    are squashed: body is shown once with an occurrence count and timestamp
    range. Pass --full to see every entry verbatim.
    """
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

    if full:
        for ts, lvl, text in entries:
            click.echo(f"{_time_part(ts)} {lvl:8s} {text}")
        return

    # Squash duplicates: key=(level, body). Preserve first-occurrence order.
    groups: OrderedDict[tuple[str, str], list[str]] = OrderedDict()
    for ts, lvl, text in entries:
        groups.setdefault((lvl, text), []).append(ts)

    squashed = sum(1 for tss in groups.values() if len(tss) > 1)
    for (lvl, text), tss in groups.items():
        if len(tss) == 1:
            click.echo(f"{_time_part(tss[0])} {lvl:8s} {text}")
            continue
        first, last = _time_part(tss[0]), _time_part(tss[-1])
        summary = _body_summary(text)
        click.echo(f"{first}..{last} {lvl:8s} (x{len(tss)}) {summary}")

    if squashed:
        click.echo(
            f"\n({squashed} duplicate group(s) squashed; pass --full for verbatim output)"
        )
