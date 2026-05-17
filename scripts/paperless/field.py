"""Custom field management."""

from __future__ import annotations

import click

from paperless._click import HelpfulGroup
from paperless._client import open_client, run_async


@click.group(cls=HelpfulGroup)
def cli() -> None:
    """List, create, and delete custom field definitions."""


@cli.command("list")
def list_cmd() -> None:
    """List all custom field definitions."""

    async def _list():
        async with open_client() as p:
            return await p.custom_fields.as_list()

    items = run_async(_list())
    if not items:
        click.echo("no custom fields")
        return
    for f in sorted(items, key=lambda x: x.name.lower()):
        click.echo(f"#{f.id} {f.name} (type: {f.data_type})")


@cli.command()
@click.argument("name")
@click.argument("data_type")
def create(name: str, data_type: str) -> None:
    """Create a custom field. DATA_TYPE: string, url, date, boolean, integer, float, monetary,
    document_link, select."""

    async def _create():
        async with open_client() as p:
            draft = p.custom_fields.create()
            draft.name = name
            draft.data_type = data_type
            return await p.custom_fields.save(draft)

    pk = run_async(_create())
    click.echo(f"created custom field #{pk}: {name} ({data_type})")


@cli.command()
@click.argument("field_id", type=int)
def delete(field_id: int) -> None:
    """Delete a custom field definition by ID."""

    async def _delete():
        async with open_client() as p:
            item = await p.custom_fields(field_id)
            await p.custom_fields.delete(item)
            return item.name

    name = run_async(_delete())
    click.echo(f"deleted custom field #{field_id}: {name}")
