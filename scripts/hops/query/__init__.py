"""Query domain: VictoriaMetrics and VictoriaLogs queries."""

from __future__ import annotations

import click

from hops.query.metrics import cli as metrics_cli
from hops.query.logs import cli as logs_cli


@click.group()
def cli():
    """Query metrics (VictoriaMetrics) and logs (VictoriaLogs)."""


cli.add_command(metrics_cli, "metrics")
cli.add_command(logs_cli, "logs")
