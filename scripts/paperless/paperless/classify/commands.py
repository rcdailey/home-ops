"""Classification workflow commands."""

from __future__ import annotations

import re
import unicodedata

import click
import ftfy
import yake

from paperless._client import open_client, run_async
from paperless.classify import cli

AI_CLASSIFIED_TAG = "ai-classified"
CONTENT_LIMIT = 2000
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


async def _ensure_tag(p) -> int:
    """Ensure ai-classified tag exists and return its ID."""
    tags = await p.tags.as_list()
    for t in tags:
        if t.name == AI_CLASSIFIED_TAG:
            return t.id
    draft = p.tags.create()
    draft.name = AI_CLASSIFIED_TAG
    draft.matching_algorithm = 0  # None (never auto-assign)
    draft.match = ""
    draft.is_insensitive = False
    draft.is_inbox_tag = False
    draft.color = "#a6cee3"
    pk = await p.tags.save(draft)
    return pk


async def _get_tag_id(p) -> int | None:
    """Get ai-classified tag ID if it exists, else None."""
    tags = await p.tags.as_list()
    for t in tags:
        if t.name == AI_CLASSIFIED_TAG:
            return t.id
    return None


@cli.command()
@click.option("-n", "--limit", default=25, type=int, help="Max documents to show.")
def inbox(limit: int) -> None:
    """List documents pending classification (missing ai-classified tag)."""

    async def _inbox():
        async with open_client() as p:
            tag_id = await _get_tag_id(p)
            results = []
            async for doc in p.documents:
                doc_tags = doc.tags or []
                if tag_id is None or tag_id not in doc_tags:
                    results.append(doc)
                    if len(results) >= limit:
                        break
            # Resolve names for display
            all_types = {t.id: t.name for t in await p.document_types.as_list()}
            all_corrs = {c.id: c.name for c in await p.correspondents.as_list()}
            all_tags = {t.id: t.name for t in await p.tags.as_list()}
            return results, all_types, all_corrs, all_tags

    docs, types, corrs, tags = run_async(_inbox())
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
        doc_tags = [t for t in (doc.tags or []) if tags.get(t, "") != AI_CLASSIFIED_TAG]
        if not doc_tags:
            missing.append("tags")
        corr_name = corrs.get(doc.correspondent, "none")
        type_name = types.get(doc.document_type, "none")
        tag_names = [tags.get(t, str(t)) for t in (doc.tags or [])]
        line = f"#{doc.id} {doc.title}"
        meta = f"corr={corr_name} type={type_name} tags=[{', '.join(tag_names)}]"
        missing_str = f"missing: {', '.join(missing)}" if missing else "all fields set"
        click.echo(f"  {line}")
        click.echo(f"    {meta} | {missing_str}")


@cli.command()
@click.argument("doc_ids", nargs=-1, type=int)
@click.option("-n", "--limit", default=10, type=int, help="Max docs if no IDs given.")
def brief(doc_ids: tuple[int, ...], limit: int) -> None:
    """Output taxonomy and document content for classification."""

    async def _brief():
        async with open_client() as p:
            # Taxonomy
            all_tags = await p.tags.as_list()
            all_types = await p.document_types.as_list()
            all_corrs = await p.correspondents.as_list()
            tag_id = None
            for t in all_tags:
                if t.name == AI_CLASSIFIED_TAG:
                    tag_id = t.id
                    break

            # Determine which docs to brief
            if doc_ids:
                docs = [await p.documents(did) for did in doc_ids]
            else:
                docs = []
                async for doc in p.documents:
                    doc_tags = doc.tags or []
                    if tag_id is None or tag_id not in doc_tags:
                        docs.append(doc)
                        if len(docs) >= limit:
                            break

            return docs, all_tags, all_types, all_corrs, tag_id

    docs, all_tags, all_types, all_corrs, tag_id = run_async(_brief())

    # Print taxonomy
    click.echo("=== Taxonomy ===")
    click.echo("Correspondents:")
    for c in sorted(all_corrs, key=lambda x: x.name.lower()):
        click.echo(f"  {c.id}={c.name}")
    click.echo("Types:")
    for t in sorted(all_types, key=lambda x: x.name.lower()):
        click.echo(f"  {t.id}={t.name}")
    click.echo("Tags:")
    display_tags = [t for t in all_tags if t.name != AI_CLASSIFIED_TAG]
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
            tag_map.get(t, str(t))
            for t in (doc.tags or [])
            if tag_map.get(t) != AI_CLASSIFIED_TAG
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
            truncated = cleaned[:CONTENT_LIMIT]
            if len(cleaned) > CONTENT_LIMIT:
                truncated += f"\n[...truncated from {len(cleaned)} chars]"
            click.echo(f"Content ({len(cleaned)} chars):")
            click.echo(truncated)

            # Keywords for longer docs
            if len(cleaned) > KEYWORD_THRESHOLD:
                keywords = _extract_keywords(cleaned)
                click.echo(f"Keywords: {keywords}")
        else:
            click.echo("Content: (empty)")
        click.echo()


@cli.command()
def tag() -> None:
    """Ensure ai-classified tag exists and show its ID."""

    async def _tag():
        async with open_client() as p:
            return await _ensure_tag(p)

    tag_id = run_async(_tag())
    click.echo(f"ai-classified tag: #{tag_id}")
