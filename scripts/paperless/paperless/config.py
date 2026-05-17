"""Server configuration and connectivity."""

from __future__ import annotations

import sys

import click

from paperless._client import get_url, open_client, run_async


@click.command()
def cli() -> None:
    """Check server connectivity and report version info."""

    async def _status():
        async with open_client() as p:
            return await p.statistics()

    url = get_url()
    try:
        stats = run_async(_status())
    except Exception as exc:
        click.echo(f"cannot reach {url}: {exc}", err=True)
        sys.exit(1)

    click.echo(f"connected to {url}")
    if hasattr(stats, "documents_total"):
        click.echo(f"documents: {stats.documents_total}")
    if hasattr(stats, "documents_inbox"):
        click.echo(f"inbox: {stats.documents_inbox}")
