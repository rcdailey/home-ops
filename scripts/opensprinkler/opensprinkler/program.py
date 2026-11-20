"""Show, change, and add programs."""

from __future__ import annotations

import click

from opensprinkler._click import HelpfulGroup
from opensprinkler._client import ApiError, die, resolve_station, station_names
from opensprinkler._program import (
    WEEKDAYS,
    Program,
    describe,
    find_program,
    load_programs,
    parse_month_day,
    parse_time,
)


@click.group(cls=HelpfulGroup)
def cli() -> None:
    """Show, change, or add programs (schedules)."""


@cli.command("list")
def list_cmd() -> None:
    """List every program: enabled, weather, days, start, active dates, zone minutes."""
    try:
        names = station_names()
        for p in load_programs():
            click.echo(describe(p, names))
    except ApiError as exc:
        die(str(exc))


def _edit_options(f):
    options = [
        click.option("--days", help="Weekly days, comma-separated (e.g. wed,sat)"),
        click.option("--interval", type=int, help="Run every N days instead of weekly"),
        click.option(
            "--offset", type=int, default=0, help="Days until the first interval run"
        ),
        click.option(
            "--start", help="Single start time HH:MM (replaces all start times)"
        ),
        click.option(
            "--weather/--no-weather", default=None, help="Apply weather adjustment"
        ),
        click.option(
            "--date-range", help="Active dates MM-DD:MM-DD (wraps across new year)"
        ),
        click.option("--all-year", is_flag=True, help="Remove the date range"),
        click.option(
            "--zone",
            "zones",
            multiple=True,
            help="STATION=MINUTES (name or index; 0 removes the zone). Repeatable.",
        ),
        click.option("--dry-run", is_flag=True, help="Show the result without writing"),
    ]
    for option in reversed(options):
        f = option(f)
    return f


def _apply(p: Program, names: list[str], opts: dict) -> None:
    if opts["days"] and opts["interval"]:
        raise ApiError("use either --days or --interval")
    if opts["days"]:
        days = [d.strip().lower()[:3] for d in opts["days"].split(",")]
        bad = [d for d in days if d not in WEEKDAYS]
        if bad:
            raise ApiError(f"unknown days {bad}; use {','.join(WEEKDAYS)}")
        p.set_weekly(days)
    if opts["interval"]:
        p.set_interval(opts["interval"], opts["offset"])
    if opts["start"]:
        p.set_bit(6, True)
        p.starts = [parse_time(opts["start"]), -1, -1, -1]
    if opts["weather"] is not None:
        p.set_bit(1, opts["weather"])
    if opts["date_range"] and opts["all_year"]:
        raise ApiError("use either --date-range or --all-year")
    if opts["date_range"]:
        start, end = opts["date_range"].split(":")
        p.set_bit(7, True)
        p.date_range = [1, parse_month_day(start), parse_month_day(end)]
    if opts["all_year"]:
        p.set_bit(7, False)
        p.date_range = [0, 33, 415]
    for spec in opts["zones"]:
        ref, _, minutes = spec.rpartition("=")
        if not ref:
            raise ApiError(f"bad --zone {spec!r}; use STATION=MINUTES")
        p.durations[resolve_station(ref, names)] = round(float(minutes) * 60)


def _commit(p: Program, names: list[str], dry_run: bool) -> None:
    if dry_run:
        click.echo("dry run, not written:")
        click.echo(describe(p, names))
        return
    p.write()
    saved = find_program(p.name, load_programs())
    click.echo(describe(saved, names))


@cli.command("set")
@click.argument("program")
@_edit_options
def set_cmd(program: str, **opts) -> None:
    """Change PROGRAM (name or index); unspecified fields and the enable bit are kept."""
    try:
        names = station_names()
        p = find_program(program, load_programs())
        _apply(p, names, opts)
        _commit(p, names, opts["dry_run"])
    except (ApiError, ValueError) as exc:
        die(str(exc))


@cli.command("add")
@click.argument("name")
@_edit_options
def add_cmd(name: str, **opts) -> None:
    """Add a disabled program NAME; needs --days or --interval, --start, and --zone."""
    try:
        names = station_names()
        if any(p.name.lower() == name.lower() for p in load_programs()):
            raise ApiError(f"a program named {name!r} already exists")
        if (
            not (opts["days"] or opts["interval"])
            or not opts["start"]
            or not opts["zones"]
        ):
            raise ApiError("add needs --days or --interval, --start, and --zone")
        p = Program(-1, 0, 0, 0, [0, 0, 0, 0], [0] * len(names), name)
        _apply(p, names, opts)
        _commit(p, names, opts["dry_run"])
    except (ApiError, ValueError) as exc:
        die(str(exc))
