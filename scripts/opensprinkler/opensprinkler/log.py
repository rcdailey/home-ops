"""Read the watering log."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

import click

from opensprinkler._client import ApiError, call, die

SPECIAL_PIDS = {99: "manual", 254: "run-once"}


def _epoch(day: date) -> int:
    # The controller stamps logs in local time expressed as epoch seconds.
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())


@click.command()
@click.option(
    "--from",
    "start",
    type=click.DateTime(["%Y-%m-%d"]),
    help="First day (default: 7 days ago)",
)
@click.option(
    "--to", "end", type=click.DateTime(["%Y-%m-%d"]), help="Last day (default: today)"
)
@click.option(
    "--runs", is_flag=True, help="List each zone run instead of a per-program summary"
)
def cli(start: datetime | None, end: datetime | None, runs: bool) -> None:
    """Summarize completed zone runs per program, or list them with --runs.

    Times are controller-local. Minutes are actual run time after adjustments.
    """
    last = (end or datetime.now()).date()
    first = start.date() if start else last - timedelta(days=7)
    try:
        records = call(
            "jl", {"start": _epoch(first), "end": _epoch(last + timedelta(days=1))}
        )
        names = call("jn")["snames"]
        programs = [pd[5] for pd in call("jp")["pd"]]
    except ApiError as exc:
        die(str(exc))
    rows = [
        r for r in records if isinstance(r, list) and len(r) >= 4 and r[1] < len(names)
    ]
    if not rows:
        click.echo(f"no runs {first} to {last}")
        return

    def program_name(pid: int) -> str:
        return SPECIAL_PIDS.get(pid) or (
            programs[pid - 1] if 0 < pid <= len(programs) else f"#{pid}"
        )

    if runs:
        for pid, sid, seconds, ended in sorted(rows, key=lambda r: r[3])[-200:]:
            stamp = datetime.fromtimestamp(ended, UTC).strftime("%m-%d %H:%M")
            click.echo(f"{stamp} {program_name(pid)}: {names[sid]} {seconds / 60:.1f}m")
        return

    summary: dict[str, dict] = defaultdict(
        lambda: {"runs": 0, "seconds": 0, "days": set()}
    )
    for pid, _sid, seconds, ended in rows:
        entry = summary[program_name(pid)]
        entry["runs"] += 1
        entry["seconds"] += seconds
        entry["days"].add(datetime.fromtimestamp(ended, UTC).strftime("%m-%d"))
    click.echo(f"{first} to {last}:")
    for name, e in summary.items():
        days = ",".join(sorted(e["days"]))
        click.echo(
            f"  {name}: {e['runs']} zone runs, {e['seconds'] / 3600:.1f} h, days {days}"
        )
