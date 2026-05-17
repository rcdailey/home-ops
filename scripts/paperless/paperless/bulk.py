"""Bulk document operations."""

from __future__ import annotations

import click

from paperless._click import HelpfulGroup
from paperless._client import open_client, run_async


def _parse_ids(doc_ids: str) -> list[int]:
    """Parse comma-separated document IDs."""
    return [int(x.strip()) for x in doc_ids.split(",")]


@click.group(cls=HelpfulGroup)
def cli() -> None:
    """Bulk operations on multiple documents."""


@cli.command()
@click.argument("doc_ids", type=str)
@click.argument("tag_id", type=int)
def tag(doc_ids: str, tag_id: int) -> None:
    """Add a tag to documents. DOC_IDS is comma-separated."""

    async def _tag():
        async with open_client() as p:
            ids = _parse_ids(doc_ids)
            await p.documents.bulk_edit.add_tag(ids, tag_id)
            return ids

    ids = run_async(_tag())
    click.echo(f"added tag #{tag_id} to {len(ids)} documents")


@cli.command()
@click.argument("doc_ids", type=str)
@click.argument("tag_id", type=int)
def untag(doc_ids: str, tag_id: int) -> None:
    """Remove a tag from documents. DOC_IDS is comma-separated."""

    async def _untag():
        async with open_client() as p:
            ids = _parse_ids(doc_ids)
            await p.documents.bulk_edit.remove_tag(ids, tag_id)
            return ids

    ids = run_async(_untag())
    click.echo(f"removed tag #{tag_id} from {len(ids)} documents")


@cli.command("set-type")
@click.argument("doc_ids", type=str)
@click.argument("type_id", type=int)
def set_type(doc_ids: str, type_id: int) -> None:
    """Set document type on documents. DOC_IDS is comma-separated."""

    async def _set():
        async with open_client() as p:
            ids = _parse_ids(doc_ids)
            await p.documents.bulk_edit.set_document_type(ids, type_id)
            return ids

    ids = run_async(_set())
    click.echo(f"set document type #{type_id} on {len(ids)} documents")


@cli.command("set-correspondent")
@click.argument("doc_ids", type=str)
@click.argument("correspondent_id", type=int)
def set_correspondent(doc_ids: str, correspondent_id: int) -> None:
    """Set correspondent on documents. DOC_IDS is comma-separated."""

    async def _set():
        async with open_client() as p:
            ids = _parse_ids(doc_ids)
            await p.documents.bulk_edit.set_correspondent(ids, correspondent_id)
            return ids

    ids = run_async(_set())
    click.echo(f"set correspondent #{correspondent_id} on {len(ids)} documents")


@cli.command()
@click.argument("doc_ids", type=str)
def reprocess(doc_ids: str) -> None:
    """Re-run OCR on documents. DOC_IDS is comma-separated."""

    async def _reprocess():
        async with open_client() as p:
            ids = _parse_ids(doc_ids)
            await p.documents.bulk_edit.reprocess(ids)
            return ids

    ids = run_async(_reprocess())
    click.echo(f"reprocessing {len(ids)} documents")
