"""Show stations and set cycle-and-soak."""

from __future__ import annotations

import click

from opensprinkler._click import HelpfulGroup
from opensprinkler._client import ApiError, call, die, resolve_station


def _bit(fields: list[int], index: int) -> bool:
    return bool(fields[index // 8] >> (index % 8) & 1)


@click.group(cls=HelpfulGroup)
def cli() -> None:
    """Show stations (zones) or set their cycle-and-soak limits."""


@cli.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include disabled stations")
def list_cmd(show_all: bool) -> None:
    """List stations: index, name, and non-default attributes."""
    try:
        jn = call("jn")
    except ApiError as exc:
        die(str(exc))
    masters = {call("jo").get(f"mas{s}", 0) - 1 for s in ("", "2", "3", "4")}
    for i, name in enumerate(jn["snames"]):
        disabled = _bit(jn["stn_dis"], i)
        if disabled and not show_all:
            continue
        notes = []
        if i in masters:
            notes.append("master valve")
        if disabled:
            notes.append("disabled")
        if _bit(jn["ignore_rain"], i):
            notes.append("ignores rain delay")
        enabled, cycle, soak = (jn.get("cs") or [[0, 0, 0]] * len(jn["snames"]))[i]
        if enabled:
            notes.append(f"cycle {cycle / 60:g}m, soak {soak / 60:g}m")
        click.echo(f"{i:>2} {name}" + (f": {', '.join(notes)}" if notes else ""))


@cli.command("cycle-soak")
@click.argument("stations", nargs=-1, required=True)
@click.option("--cycle", type=float, help="Maximum minutes per watering cycle (1-240)")
@click.option("--soak", type=float, help="Minimum minutes between cycles (1-240)")
@click.option("--off", is_flag=True, help="Disable cycle-and-soak")
def cycle_soak(
    stations: tuple[str, ...], cycle: float | None, soak: float | None, off: bool
) -> None:
    """Set cycle-and-soak for STATIONS (names or indices).

    A run longer than --cycle is split into near-equal cycles with at least --soak
    between them; total watering time is unchanged. Requires firmware 2.2.1(7).
    """
    if off:
        if cycle or soak:
            die("give --cycle and --soak, or --off")
        settings: dict[str, int] = {"cse": 0}
        state = "off"
    elif cycle and soak:
        settings = {"cse": 1, "csc": round(cycle * 60), "css": round(soak * 60)}
        state = f"cycle {cycle:g}m, soak {soak:g}m"
    else:
        die("give --cycle and --soak, or --off")
    try:
        names = call("jn")["snames"]
        for ref in stations:
            sid = resolve_station(ref, names)
            call("cs", {"sid": sid, **settings})
            click.echo(f"{sid} {names[sid]}: {state}")
        if call("jc").get("cserr"):
            die("controller reports a cycle-and-soak configuration error (jc.cserr=1)")
    except ApiError as exc:
        die(str(exc))
