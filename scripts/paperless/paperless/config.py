"""Server configuration and connectivity."""

from __future__ import annotations

import click

from paperless._client import get_url, open_client, run_async


@click.command()
def cli() -> None:
    """Check server connectivity and report version info."""

    async def _status():
        async with open_client() as p:
            return await p.statistics()

    # run_async already reports connectivity/API failures and exits non-zero,
    # so reaching the next line means the call succeeded.
    url = get_url()
    stats = run_async(_status())

    click.echo(f"connected to {url}")
    if hasattr(stats, "documents_total"):
        click.echo(f"documents: {stats.documents_total}")
    if hasattr(stats, "documents_inbox"):
        click.echo(f"inbox: {stats.documents_inbox}")
