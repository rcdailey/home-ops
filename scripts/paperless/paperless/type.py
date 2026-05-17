"""Document type management."""

from __future__ import annotations

import click

from paperless._click import HelpfulGroup
from paperless._client import open_client, run_async
from paperless._permissions import set_family_permissions


@click.group(cls=HelpfulGroup)
def cli() -> None:
    """List, create, and delete document types."""


@cli.command("list")
def list_cmd() -> None:
    """List all document types with document counts."""

    async def _list():
        async with open_client() as p:
            return await p.document_types.as_list()

    items = run_async(_list())
    if not items:
        click.echo("no document types")
        return
    for dt in sorted(items, key=lambda x: x.name.lower()):
        click.echo(f"#{dt.id} {dt.name} ({dt.document_count} docs)")


@cli.command()
@click.argument("name")
def create(name: str) -> None:
    """Create a new document type."""

    async def _create():
        async with open_client() as p:
            draft = p.document_types.create()
            draft.name = name
            draft.match = ""
            draft.matching_algorithm = 0
            draft.is_insensitive = True
            pk = await p.document_types.save(draft)
        await set_family_permissions("document_types", pk)
        return pk

    pk = run_async(_create())
    click.echo(f"created document type #{pk}: {name}")


@cli.command()
@click.argument("type_id", type=int)
def delete(type_id: int) -> None:
    """Delete a document type by ID."""

    async def _delete():
        async with open_client() as p:
            item = await p.document_types(type_id)
            await p.document_types.delete(item)
            return item.name

    name = run_async(_delete())
    click.echo(f"deleted document type #{type_id}: {name}")
