"""Root CLI group."""

from __future__ import annotations

import click

from opensprinkler._click import HelpfulGroup
from opensprinkler.log import cli as log
from opensprinkler.program import cli as program
from opensprinkler.raw import cli as raw
from opensprinkler.station import cli as station
from opensprinkler.weather import cli as weather


@click.group(cls=HelpfulGroup, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(
    version=__import__("opensprinkler").__version__, prog_name="opensprinkler"
)
def cli() -> None:
    """OpenSprinkler controller API wrapper.

    Talks directly to the controller at 192.168.2.108 with OPENSPRINKLER_PASSWORD
    (from the repo's encrypted mise secrets). Home Assistant toggles program enable
    switches; this tool edits everything else.
    """


cli.add_command(program, "program")
cli.add_command(station, "station")
cli.add_command(weather, "weather")
cli.add_command(log, "log")
cli.add_command(raw, "raw")
