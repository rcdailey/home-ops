"""Query domain: VictoriaMetrics and VictoriaLogs queries."""

from __future__ import annotations

import click

from hops.query.logs import cli as logs_cli
from hops.query.metrics import cli as metrics_cli

# The query group exposes all metrics commands directly (no `metrics`
# subgroup) because raw PromQL is the most common operation and triple-
# nesting (`query metrics query`) wastes keystrokes. Logs keeps its own
# subgroup since it has a distinct filter surface.


@click.group()
def cli():
    """Query metrics (VictoriaMetrics) and logs (VictoriaLogs)."""


# Flatten every command from the metrics group into the query group
for name, cmd in list(metrics_cli.commands.items()):
    cli.add_command(cmd, name)

cli.add_command(logs_cli, "logs")
