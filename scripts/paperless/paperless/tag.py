"""Tag management."""

from __future__ import annotations

import click

from paperless._click import HelpfulGroup
from paperless._client import open_client, run_async
from paperless._permissions import create_object


@click.group(cls=HelpfulGroup)
def cli() -> None:
    """List, create, and delete tags."""


@cli.command("list")
def list_cmd() -> None:
    """List all tags with document counts."""

    async def _list():
        async with open_client() as p:
            return await p.tags.as_list()

    tags = run_async(_list())
    if not tags:
        click.echo("no tags")
        return
    for t in sorted(tags, key=lambda x: x.name.lower()):
        click.echo(f"#{t.id} {t.name} ({t.document_count} docs)")


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.option("--color", default=None, help="Hex color (e.g. #a6cee3).")
@click.option("--inbox", is_flag=True, help="Mark as inbox tag.")
def create(names: tuple[str, ...], color: str | None, inbox: bool) -> None:
    """Create one or more tags."""
    for name in names:
        pk = run_async(
            create_object(
                "tags",
                {"name": name, "color": color or "#a6cee3", "is_inbox_tag": inbox},
            )
        )
        click.echo(f"created tag #{pk}: {name}")


@cli.command()
@click.argument("tag_id", type=int)
def delete(tag_id: int) -> None:
    """Delete a tag by ID."""

    async def _delete():
        async with open_client() as p:
            tag = await p.tags(tag_id)
            await p.tags.delete(tag)
            return tag.name

    name = run_async(_delete())
    click.echo(f"deleted tag #{tag_id}: {name}")
