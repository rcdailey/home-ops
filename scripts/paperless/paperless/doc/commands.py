"""Document subcommands."""

from __future__ import annotations

from pathlib import Path

import click

from paperless._client import open_client, run_async
from paperless.doc import cli


@cli.command("list")
@click.option("-n", "--limit", default=25, type=int, help="Max documents to return.")
@click.option(
    "--tag", "tag_ids", multiple=True, type=int, help="Filter by tag ID (repeatable)."
)
@click.option(
    "--type", "type_id", default=None, type=int, help="Filter by document type ID."
)
@click.option(
    "--correspondent",
    "corr_id",
    default=None,
    type=int,
    help="Filter by correspondent ID.",
)
@click.option("--inbox", is_flag=True, help="Show only inbox documents.")
def list_cmd(
    limit: int,
    tag_ids: tuple[int, ...],
    type_id: int | None,
    corr_id: int | None,
    inbox: bool,
) -> None:
    """List documents with optional filters."""

    async def _list():
        async with open_client() as p:
            kwargs = {}
            if tag_ids:
                kwargs["tags__id__all"] = ",".join(str(t) for t in tag_ids)
            if type_id is not None:
                kwargs["document_type__id"] = type_id
            if corr_id is not None:
                kwargs["correspondent__id"] = corr_id
            if inbox:
                kwargs["is_in_inbox"] = True

            results = []
            if kwargs:
                async with p.documents.filter(**kwargs) as docs:
                    async for doc in docs:
                        results.append(doc)
                        if len(results) >= limit:
                            break
            else:
                async for doc in p.documents:
                    results.append(doc)
                    if len(results) >= limit:
                        break
            return results

    docs = run_async(_list())
    if not docs:
        click.echo("no documents found")
        return
    for d in docs:
        parts = [f"#{d.id} {d.title}"]
        if hasattr(d, "correspondent") and d.correspondent:
            parts.append(f"corr={d.correspondent}")
        if hasattr(d, "document_type") and d.document_type:
            parts.append(f"type={d.document_type}")
        if hasattr(d, "tags") and d.tags:
            parts.append(f"tags={d.tags}")
        click.echo(" | ".join(parts))


@cli.command()
@click.argument("doc_id", type=int)
@click.option("--full", is_flag=True, help="Show full content without truncation.")
def show(doc_id: int, full: bool) -> None:
    """Show full document details."""

    async def _show():
        async with open_client() as p:
            doc = await p.documents(doc_id)
            tag_names = []
            if doc.tags:
                for tid in doc.tags:
                    try:
                        t = await p.tags(tid)
                        tag_names.append(t.name)
                    except Exception:
                        tag_names.append(str(tid))
            corr_name = None
            if doc.correspondent:
                try:
                    c = await p.correspondents(doc.correspondent)
                    corr_name = c.name
                except Exception:
                    corr_name = str(doc.correspondent)
            type_name = None
            if doc.document_type:
                try:
                    dt = await p.document_types(doc.document_type)
                    type_name = dt.name
                except Exception:
                    type_name = str(doc.document_type)
            return doc, tag_names, corr_name, type_name

    doc, tag_names, corr_name, type_name = run_async(_show())
    click.echo(f"document #{doc.id}")
    click.echo(f"  title: {doc.title}")
    if corr_name:
        click.echo(f"  correspondent: {corr_name}")
    if type_name:
        click.echo(f"  type: {type_name}")
    if tag_names:
        click.echo(f"  tags: {', '.join(tag_names)}")
    if hasattr(doc, "created") and doc.created:
        click.echo(f"  created: {doc.created}")
    if hasattr(doc, "added") and doc.added:
        click.echo(f"  added: {doc.added}")
    if hasattr(doc, "archive_serial_number") and doc.archive_serial_number:
        click.echo(f"  asn: {doc.archive_serial_number}")
    if hasattr(doc, "storage_path") and doc.storage_path:
        click.echo(f"  storage path: {doc.storage_path}")
    if hasattr(doc, "custom_fields") and doc.custom_fields:
        click.echo("  custom fields:")
        for cf in doc.custom_fields:
            click.echo(f"    {cf.field}: {cf.value}")
    if hasattr(doc, "content") and doc.content:
        if full:
            click.echo(f"  content: {doc.content}")
        else:
            preview = doc.content[:500]
            if len(doc.content) > 500:
                preview += f" [truncated at 500 of {len(doc.content)} chars]"
            click.echo(f"  content: {preview}")


@cli.command()
@click.argument("query")
@click.option("-n", "--limit", default=10, type=int, help="Max results.")
def search(query: str, limit: int) -> None:
    """Full-text search across documents."""

    async def _search():
        async with open_client() as p:
            results = []
            async for doc in p.documents.search(query):
                results.append(doc)
                if len(results) >= limit:
                    break
            return results

    docs = run_async(_search())
    if not docs:
        click.echo("no results")
        return
    for d in docs:
        parts = [f"#{d.id} {d.title}"]
        if hasattr(d, "search_hit") and d.search_hit:
            if hasattr(d.search_hit, "score") and d.search_hit.score:
                parts.append(f"score={d.search_hit.score:.2f}")
        click.echo(" | ".join(parts))


def _collect_files(path: Path, recursive: bool) -> list[Path]:
    """Collect PDF files from a directory."""
    pattern = "**/*.pdf" if recursive else "*.pdf"
    files = sorted(path.glob(pattern))
    if not files:
        from paperless._errors import die

        die(f"no PDF files found in {path}")
    return files


def _upload_single(
    path: Path,
    title: str | None,
    tag_ids: tuple[int, ...],
    type_id: int | None,
    corr_id: int | None,
) -> None:
    """Upload a single file to Paperless."""
    content = path.read_bytes()
    filename = path.name

    async def _upload():
        async with open_client() as p:
            kwargs = {"document": content, "filename": filename}
            if title:
                kwargs["title"] = title
            if tag_ids:
                kwargs["tags"] = list(tag_ids)
            if type_id is not None:
                kwargs["document_type"] = type_id
            if corr_id is not None:
                kwargs["correspondent"] = corr_id
            draft = p.documents.create(**kwargs)
            return await p.documents.save(draft)

    task_id = run_async(_upload())
    click.echo(f"uploaded {filename}, task: {task_id}")


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--title", default=None, help="Document title (defaults to filename).")
@click.option("--tag", "tag_ids", multiple=True, type=int, help="Tag ID (repeatable).")
@click.option("--type", "type_id", default=None, type=int, help="Document type ID.")
@click.option(
    "--correspondent", "corr_id", default=None, type=int, help="Correspondent ID."
)
@click.option("-r", "--recursive", is_flag=True, help="Recurse into subdirectories.")
def upload(
    path: str,
    title: str | None,
    tag_ids: tuple[int, ...],
    type_id: int | None,
    corr_id: int | None,
    recursive: bool,
) -> None:
    """Upload a document file or all PDFs in a directory."""
    from paperless._errors import die

    target = Path(path)

    if target.is_dir():
        if title:
            die("--title cannot be used with directory uploads")
        files = _collect_files(target, recursive)
        click.echo(f"uploading {len(files)} file(s) from {target}")
        for f in files:
            _upload_single(f, None, tag_ids, type_id, corr_id)
    else:
        _upload_single(target, title, tag_ids, type_id, corr_id)


@cli.command()
@click.argument("doc_id", type=int)
@click.option("--title", default=None, help="New title.")
@click.option(
    "--tag",
    "tag_ids",
    multiple=True,
    type=int,
    help="Tag ID (repeatable). Replaces all tags.",
)
@click.option(
    "--add-tag", "add_tags", multiple=True, type=int, help="Tag ID to add (repeatable)."
)
@click.option(
    "--remove-tag",
    "remove_tags",
    multiple=True,
    type=int,
    help="Tag ID to remove (repeatable).",
)
@click.option("--type", "type_id", default=None, type=int, help="Document type ID.")
@click.option(
    "--correspondent", "corr_id", default=None, type=int, help="Correspondent ID."
)
@click.option("--clear-correspondent", is_flag=True, help="Remove correspondent.")
@click.option("--clear-type", is_flag=True, help="Remove document type.")
def update(
    doc_id: int,
    title: str | None,
    tag_ids: tuple[int, ...],
    add_tags: tuple[int, ...],
    remove_tags: tuple[int, ...],
    type_id: int | None,
    corr_id: int | None,
    clear_correspondent: bool,
    clear_type: bool,
) -> None:
    """Update document metadata."""
    from paperless._permissions import ensure_inbox_tag

    async def _update():
        inbox_tag_id = await ensure_inbox_tag()
        async with open_client() as p:
            doc = await p.documents(doc_id)
            if title:
                doc.title = title
            if tag_ids:
                # Replace semantics: exclude inbox tag from replacement set
                doc.tags = list(set(tag_ids) - {inbox_tag_id})
            elif add_tags or remove_tags:
                current = set(doc.tags or [])
                current.update(add_tags)
                current -= set(remove_tags)
                current.discard(inbox_tag_id)
                doc.tags = list(current)
            else:
                # No tag flags: remove inbox tag to signal classification done
                current = set(doc.tags or [])
                current.discard(inbox_tag_id)
                doc.tags = list(current)
            if type_id is not None:
                doc.document_type = type_id
            if corr_id is not None:
                doc.correspondent = corr_id
            if clear_correspondent:
                doc.correspondent = None
            if clear_type:
                doc.document_type = None
            await p.documents.update(doc)
            return doc.title

    name = run_async(_update())
    click.echo(f"updated document #{doc_id}: {name}")


@cli.command()
@click.argument("doc_id", type=int)
def suggest(doc_id: int) -> None:
    """Show classifier suggestions for a document."""

    async def _suggest():
        async with open_client() as p:
            return await p.documents.suggestions(doc_id)

    suggestions = run_async(_suggest())
    click.echo(f"suggestions for document #{doc_id}:")
    if hasattr(suggestions, "correspondents") and suggestions.correspondents:
        click.echo(f"  correspondents: {suggestions.correspondents}")
    if hasattr(suggestions, "tags") and suggestions.tags:
        click.echo(f"  tags: {suggestions.tags}")
    if hasattr(suggestions, "document_types") and suggestions.document_types:
        click.echo(f"  document types: {suggestions.document_types}")
    if hasattr(suggestions, "storage_paths") and suggestions.storage_paths:
        click.echo(f"  storage paths: {suggestions.storage_paths}")


@cli.command()
@click.argument("doc_id", type=int)
@click.option(
    "--original", is_flag=True, help="Download original instead of archived version."
)
@click.option("-o", "--output", default=None, type=click.Path(), help="Output path.")
def download(doc_id: int, original: bool, output: str | None) -> None:
    """Download a document file."""

    async def _download():
        async with open_client() as p:
            return await p.documents.download(doc_id, original=original)

    dl = run_async(_download())
    out_path = Path(output) if output else Path(dl.disposition_filename)
    out_path.write_bytes(dl.content)
    click.echo(f"saved to {out_path} ({len(dl.content)} bytes)")
