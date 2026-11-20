"""Show and tune weather adjustment."""

from __future__ import annotations

import json

import click

from opensprinkler._click import HelpfulGroup
from opensprinkler._client import ApiError, call, die

METHODS = {0: "manual", 1: "Zimmerman", 2: "auto rain delay", 3: "ETo", 4: "monthly"}


@click.group(cls=HelpfulGroup, invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Show weather adjustment state, or change its baseline."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(show)


@cli.command()
def show() -> None:
    """Method, baseline, current and multi-day water levels, last data, and errors.

    Only programs with weather on use the water level. Interval programs use the
    multi-day level matching their interval (1 day = first value).
    """
    try:
        jc, jo = call("jc"), call("jo")
    except ApiError as exc:
        die(str(exc))
    wto, data = jc.get("wto") or {}, jc.get("wtdata") or {}
    click.echo(
        f"method {METHODS.get(jo.get('uwt'), jo.get('uwt'))}, provider {data.get('wp')}"
    )
    click.echo(f"options {json.dumps(wto)}")
    click.echo(f"water level {jo.get('wl')}%; multi-day levels {jc.get('wls')}")
    click.echo(f"last data {json.dumps(data)}")
    click.echo(
        f"error code {jc.get('wterr')} (0 is ok); restriction {jc.get('wtrestr')}"
    )


@cli.command()
@click.argument("eto", type=float)
def baseline(eto: float) -> None:
    """Set the ETo method's baseline ETo (inches/day), keeping other weather options.

    Water level = (recent ETo - rain) / baseline. Raising it shortens every
    weather-adjusted run proportionally.
    """
    try:
        wto = dict(call("jc").get("wto") or {})
        old = wto.get("baseETo")
        wto["baseETo"] = eto
        call("co", {"wto": json.dumps(wto, separators=(",", ":"))})
        saved = call("jc").get("wto", {}).get("baseETo")
    except ApiError as exc:
        die(str(exc))
    if saved != eto:
        die(f"controller kept baseline {saved}")
    click.echo(f"baseline ETo {old} -> {saved} in/day")
