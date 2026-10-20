"""Root CLI group with auto-discovery of subcommand modules."""

from __future__ import annotations

import click

from zwave._click import AutoGroup


@click.group(
    cls=AutoGroup,
    package="zwave",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(version=__import__("zwave").__version__, prog_name="zwave")
def cli():
    """Z-Wave JS server API wrapper.

    Each command opens a temporary kubectl port-forward to the zwave-js-ui
    server WebSocket (home/svc/zwave-js-ui:3000) and closes it on exit.
    """
