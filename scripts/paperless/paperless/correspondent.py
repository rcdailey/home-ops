"""Correspondent management."""

from __future__ import annotations

import click

from paperless._click import HelpfulGroup
from paperless._client import open_client, run_async


@click.group(cls=HelpfulGroup)
def cli() -> None:
    """List, create, and delete correspondents."""


@cli.command("list")
def list_cmd() -> None:
    """List all correspondents with document counts."""

    async def _list():
        async with open_client() as p:
            return await p.correspondents.as_list()

    items = run_async(_list())
    if not items:
        click.echo("no correspondents")
        return
    for c in sorted(items, key=lambda x: x.name.lower()):
        click.echo(f"#{c.id} {c.name} ({c.document_count} docs)")


@cli.command()
@click.argument("name")
def create(name: str) -> None:
    """Create a new correspondent."""

    async def _create():
        async with open_client() as p:
            draft = p.correspondents.create()
            draft.name = name
            return await p.correspondents.save(draft)

    pk = run_async(_create())
    click.echo(f"created correspondent #{pk}: {name}")


@cli.command()
@click.argument("correspondent_id", type=int)
def delete(correspondent_id: int) -> None:
    """Delete a correspondent by ID."""

    async def _delete():
        async with open_client() as p:
            item = await p.correspondents(correspondent_id)
            await p.correspondents.delete(item)
            return item.name

    name = run_async(_delete())
    click.echo(f"deleted correspondent #{correspondent_id}: {name}")
