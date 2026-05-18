"""Classification workflow commands."""

from __future__ import annotations

import re
import sys
import unicodedata

import click
import ftfy
import yake

from paperless._client import open_client, run_async
from paperless._permissions import ensure_inbox_tag
from paperless.classify import cli

COMPACT_LIMIT = 500
FULL_LIMIT = 2000
KEYWORD_THRESHOLD = 5000


def _sanitize(text: str) -> str:
    """Clean OCR text: fix encoding, strip junk, collapse whitespace."""
    text = ftfy.fix_text(text)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]", "", text)
    text = re.sub(r"[_\.]{5,}", "", text)
    text = re.sub(r"[-=~*]{5,}", "", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_keywords(text: str, top_n: int = 10) -> str:
    """Extract top keywords with YAKE."""
    extractor = yake.KeywordExtractor(lan="en", n=2, top=top_n)
    keywords = extractor.extract_keywords(text)
    return ", ".join(kw for kw, _score in keywords)


@cli.command()
@click.option("-n", "--limit", default=25, type=int, help="Max documents to show.")
def inbox(limit: int) -> None:
    """List documents pending classification (have inbox tag)."""

    async def _inbox():
        inbox_tag_id = await ensure_inbox_tag()
        async with open_client() as p:
            results = []
            async for doc in p.documents:
                doc_tags = doc.tags or []
                if inbox_tag_id in doc_tags:
                    results.append(doc)
                    if len(results) >= limit:
                        break
            all_types = {t.id: t.name for t in await p.document_types.as_list()}
            all_corrs = {c.id: c.name for c in await p.correspondents.as_list()}
            all_tags = {t.id: t.name for t in await p.tags.as_list()}
            return results, all_types, all_corrs, all_tags, inbox_tag_id

    docs, types, corrs, tags, inbox_tag_id = run_async(_inbox())
    if not docs:
        click.echo("inbox empty")
        return
    click.echo(f"{len(docs)} documents pending classification:\n")
    for doc in docs:
        missing = []
        if not doc.correspondent:
            missing.append("correspondent")
        if not doc.document_type:
            missing.append("type")
        doc_tags = [t for t in (doc.tags or []) if t != inbox_tag_id]
        if not doc_tags:
            missing.append("tags")
        corr_name = corrs.get(doc.correspondent, "none")
        type_name = types.get(doc.document_type, "none")
        tag_names = [tags.get(t, str(t)) for t in (doc.tags or []) if t != inbox_tag_id]
        line = f"#{doc.id} {doc.title}"
        meta = f"corr={corr_name} type={type_name} tags=[{', '.join(tag_names)}]"
        missing_str = f"missing: {', '.join(missing)}" if missing else "all fields set"
        click.echo(f"  {line}")
        click.echo(f"    {meta} | {missing_str}")


@cli.command()
@click.argument("doc_ids", nargs=-1, type=int)
@click.option("-n", "--limit", default=25, type=int, help="Max docs if no IDs given.")
@click.option("--full", is_flag=True, help="Show full content (2000 chars + keywords).")
def brief(doc_ids: tuple[int, ...], limit: int, full: bool) -> None:
    """Output taxonomy and document content for classification."""

    async def _brief():
        inbox_tag_id = await ensure_inbox_tag()
        async with open_client() as p:
            # Taxonomy
            all_tags = await p.tags.as_list()
            all_types = await p.document_types.as_list()
            all_corrs = await p.correspondents.as_list()

            # Determine which docs to brief
            if doc_ids:
                docs = [await p.documents(did) for did in doc_ids]
            else:
                docs = []
                async for doc in p.documents:
                    doc_tags = doc.tags or []
                    if inbox_tag_id in doc_tags:
                        docs.append(doc)
                        if len(docs) >= limit:
                            break

            return docs, all_tags, all_types, all_corrs, inbox_tag_id

    docs, all_tags, all_types, all_corrs, inbox_tag_id = run_async(_brief())

    # Print taxonomy
    click.echo("=== Taxonomy ===")
    click.echo("Correspondents:")
    for c in sorted(all_corrs, key=lambda x: x.name.lower()):
        click.echo(f"  {c.id}={c.name}")
    click.echo("Types:")
    for t in sorted(all_types, key=lambda x: x.name.lower()):
        click.echo(f"  {t.id}={t.name}")
    click.echo("Tags:")
    display_tags = [t for t in all_tags if t.id != inbox_tag_id]
    for t in sorted(display_tags, key=lambda x: x.name.lower()):
        click.echo(f"  {t.id}={t.name}")
    click.echo()

    if not docs:
        click.echo("no documents to brief")
        return

    # Build lookup maps
    type_map = {t.id: t.name for t in all_types}
    corr_map = {c.id: c.name for c in all_corrs}
    tag_map = {t.id: t.name for t in all_tags}

    for doc in docs:
        click.echo(f"=== Document #{doc.id} ===")
        click.echo(f"Title: {doc.title}")
        corr_name = corr_map.get(doc.correspondent, "none")
        type_name = type_map.get(doc.document_type, "none")
        doc_tags = [
            tag_map.get(t, str(t)) for t in (doc.tags or []) if t != inbox_tag_id
        ]
        click.echo(
            f"Current: correspondent={corr_name}, type={type_name}, "
            f"tags=[{', '.join(doc_tags)}]"
        )
        if hasattr(doc, "created") and doc.created:
            click.echo(f"Created: {doc.created}")

        # Content processing
        content = getattr(doc, "content", "") or ""
        if content:
            cleaned = _sanitize(content)
            limit_chars = FULL_LIMIT if full else COMPACT_LIMIT
            truncated = cleaned[:limit_chars]
            if len(cleaned) > limit_chars:
                truncated += f"\n[...truncated from {len(cleaned)} chars]"
            click.echo(f"Content ({len(cleaned)} chars):")
            click.echo(truncated)

            # Keywords for longer docs (full mode only)
            if full and len(cleaned) > KEYWORD_THRESHOLD:
                keywords = _extract_keywords(cleaned)
                click.echo(f"Keywords: {keywords}")
        else:
            click.echo("Content: (empty)")
        click.echo()


def _parse_apply_line(line: str) -> dict[str, object]:
    """Parse a pipe-delimited classification line.

    Format: id|correspondent_id|type_id|tag_ids|title
    Empty correspondent_id or type_id means skip. Empty tag_ids means no tags.
    """
    parts = line.split("|")
    if len(parts) != 5:
        msg = f"expected 5 pipe-delimited fields, got {len(parts)}"
        raise ValueError(msg)
    doc_id_str, corr_str, type_str, tags_str, title = parts
    result: dict[str, object] = {"doc_id": int(doc_id_str.strip())}
    corr_str = corr_str.strip()
    if corr_str:
        result["correspondent"] = int(corr_str)
    type_str = type_str.strip()
    if type_str:
        result["type"] = int(type_str)
    tags_str = tags_str.strip()
    if tags_str:
        result["tags"] = [int(t.strip()) for t in tags_str.split(",")]
    else:
        result["tags"] = []
    title = title.strip()
    if title:
        result["title"] = title
    return result


@cli.command()
def apply() -> None:
    """Bulk-classify documents from stdin (pipe-delimited).

    Format: id|correspondent_id|type_id|tag_ids|title

    Correspondent and type fields can be empty to skip. Tag IDs are
    comma-separated within the field. The inbox tag is removed automatically.

    Example input:
    278|18|7|7|W-2 Wage and Tax Statement (2025)
    248||7|7,3|W-4 Employee Withholding Certificate (2023)
    """
    lines = [
        line.strip()
        for line in sys.stdin
        if line.strip() and not line.strip().startswith("#")
    ]
    if not lines:
        click.echo("no input lines", err=True)
        return

    entries = []
    for i, line in enumerate(lines, 1):
        try:
            entries.append(_parse_apply_line(line))
        except ValueError as exc:
            click.echo(f"line {i}: {exc} -- {line!r}", err=True)
            raise SystemExit(1) from None

    async def _apply():
        inbox_tag_id = await ensure_inbox_tag()
        async with open_client() as p:
            all_corrs = {c.id: c.name for c in await p.correspondents.as_list()}
            all_types = {t.id: t.name for t in await p.document_types.as_list()}
            all_tags_map = {t.id: t.name for t in await p.tags.as_list()}
            results = []
            for entry in entries:
                doc_id = entry["doc_id"]
                try:
                    doc = await p.documents(doc_id)
                    if "title" in entry:
                        doc.title = entry["title"]
                    if "correspondent" in entry:
                        doc.correspondent = entry["correspondent"]
                    if "type" in entry:
                        doc.document_type = entry["type"]
                    tags = set(entry.get("tags", []))
                    tags.discard(inbox_tag_id)
                    doc.tags = list(tags)
                    await p.documents.update(doc)
                    corr_name = all_corrs.get(entry.get("correspondent"), "none")
                    type_name = all_types.get(entry.get("type"), "none")
                    tag_names = [
                        all_tags_map.get(t, str(t))
                        for t in entry.get("tags", [])
                        if t != inbox_tag_id
                    ]
                    results.append(
                        (doc_id, doc.title, corr_name, type_name, tag_names, None)
                    )
                except Exception as exc:
                    results.append((doc_id, None, None, None, None, str(exc)))
            return results

    results = run_async(_apply())
    errors = 0
    for doc_id, title, corr_name, type_name, tag_names, err in results:
        if err:
            click.echo(f"#{doc_id}: error: {err}", err=True)
            errors += 1
        else:
            tags_str = ", ".join(tag_names) if tag_names else "none"
            click.echo(
                f"#{doc_id}: {title} | corr={corr_name} | type={type_name} | tags={tags_str}"
            )
    click.echo(f"\n{len(results) - errors}/{len(results)} classified")
    if errors:
        raise SystemExit(1)
