#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "ftfy==6.3.1",
#   "httpx==0.28.1",
#   "opentelemetry-api==1.44.0",
#   "pydantic==2.12.5",
#   "pydantic-ai-slim[openai]==2.0.0",
# ]
# ///

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, Self, TypeVar
from urllib.parse import urlsplit

import ftfy
import httpx
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_ai import Agent, ModelRetry, ModelSettings, RunContext, UsageLimits
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

COMPACT_CONTENT_LIMIT = 500
FULL_CONTENT_LIMIT = 2_000
DOCUMENT_LIMIT = 25
DOCUMENT_TYPE_LIMIT = 25
TAG_LIMIT = 20
INBOX_TAG_NAME = "inbox"
FAMILY_GROUP_NAME = "family"
DEFAULT_TAG_COLOR = "#a6cee3"
LOGGER = logging.getLogger("paperless-classifier")
TRACER = trace.get_tracer("paperless-classifier")


class JsonFormatter(logging.Formatter):
    """Format standard logging records as one-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, UTC).isoformat(
            timespec="milliseconds"
        )
        payload: dict[str, Any] = {
            "timestamp": timestamp.replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        trace_id = getattr(record, "otelTraceID", None)
        span_id = getattr(record, "otelSpanID", None)
        if trace_id and trace_id != "0":
            payload["trace_id"] = trace_id
            payload["span_id"] = span_id
            payload["trace_sampled"] = getattr(record, "otelTraceSampled", False)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class TaxonomyItem(ApiModel):
    id: int
    name: str


class TagItem(TaxonomyItem):
    is_inbox_tag: bool = False


class PaperlessDocument(ApiModel):
    id: int
    title: str
    content: str = ""
    created: str | None = None
    correspondent: int | None = None
    document_type: int | None = None
    tags: tuple[int, ...] = ()


class Taxonomy(StrictModel):
    correspondents: tuple[TaxonomyItem, ...]
    document_types: tuple[TaxonomyItem, ...]
    tags: tuple[TaxonomyItem, ...]
    inbox_tag_id: int


class Classification(StrictModel):
    kind: Literal["classification"]
    document_id: int
    correspondent: str = Field(min_length=1, max_length=100)
    document_type: str = Field(min_length=1, max_length=100)
    tags: tuple[str, ...] = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: tuple[str, ...]) -> tuple[str, ...]:
        normalized = [normalize_name(tag) for tag in tags]
        if len(normalized) != len(set(normalized)):
            raise ValueError("tags must be unique")
        return tags


class DeferredClassification(StrictModel):
    kind: Literal["needs_full_content"]
    document_id: int
    reason: str = Field(min_length=1, max_length=200)


Decision = Classification | DeferredClassification


class ClassificationBatch(StrictModel):
    decisions: tuple[Decision, ...]


@dataclass(frozen=True)
class ValidationContext:
    expected_document_ids: frozenset[int]
    taxonomy: Taxonomy
    allow_deferred: bool


@dataclass(frozen=True)
class Settings:
    paperless_url: str
    paperless_token: str
    deepseek_api_key: str
    deepseek_model: str

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            paperless_url=required_environment("PAPERLESS_URL"),
            paperless_token=required_environment("PAPERLESS_TOKEN"),
            deepseek_api_key=required_environment("DEEPSEEK_API_KEY"),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        )


T = TypeVar("T", bound=BaseModel)


class PaperlessClient:
    def __init__(self, base_url: str, token: str) -> None:
        normalized_url = normalize_base_url(base_url)
        parsed_url = urlsplit(normalized_url)
        if parsed_url.hostname is None:
            raise ValueError("Paperless URL has no hostname")
        self._host = parsed_url.hostname
        self._client = httpx.AsyncClient(
            base_url=normalized_url,
            headers={"Authorization": f"Token {token}"},
            timeout=httpx.Timeout(30, connect=10),
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json_body: Mapping[str, object] | None = None,
    ) -> Any:
        response = await self._client.request(
            method,
            path,
            params=params,
            json=json_body,
        )
        response.raise_for_status()
        if response.status_code == httpx.codes.NO_CONTENT:
            return None
        return response.json()

    async def list_objects(
        self,
        path: str,
        model: type[T],
        *,
        params: Mapping[str, str | int] | None = None,
        limit: int | None = None,
    ) -> tuple[T, ...]:
        items: list[T] = []
        url: str | None = path
        query = params
        while url:
            data = await self.request("GET", url, params=query)
            page_items, next_url = parse_page(data)
            url = (
                normalize_page_url(next_url, expected_host=self._host)
                if next_url
                else None
            )
            items.extend(model.model_validate(item) for item in page_items)
            if limit is not None and len(items) >= limit:
                return tuple(items[:limit])
            query = None
        return tuple(items)

    async def get_document(self, document_id: int) -> PaperlessDocument:
        data = await self.request("GET", f"api/documents/{document_id}/")
        return PaperlessDocument.model_validate(data)

    async def list_inbox_documents(self) -> tuple[PaperlessDocument, ...]:
        summaries = await self.list_objects(
            "api/documents/",
            PaperlessDocument,
            params={"is_in_inbox": "true", "page_size": DOCUMENT_LIMIT},
            limit=DOCUMENT_LIMIT,
        )
        return tuple(
            await asyncio.gather(*(self.get_document(item.id) for item in summaries))
        )

    async def load_taxonomy(self) -> Taxonomy:
        correspondents, document_types, tags = await asyncio.gather(
            self.list_objects("api/correspondents/", TaxonomyItem),
            self.list_objects("api/document_types/", TaxonomyItem),
            self.list_objects("api/tags/", TagItem),
        )
        inbox_tag = next(
            (
                tag
                for tag in tags
                if tag.is_inbox_tag or normalize_name(tag.name) == INBOX_TAG_NAME
            ),
            None,
        )
        if inbox_tag is None:
            inbox_tag = await self.create_tag(INBOX_TAG_NAME, is_inbox=True)
            tags = (
                *tags,
                TagItem(id=inbox_tag.id, name=inbox_tag.name, is_inbox_tag=True),
            )
        visible_tags = tuple(
            TaxonomyItem(id=tag.id, name=tag.name)
            for tag in tags
            if tag.id != inbox_tag.id
        )
        return Taxonomy(
            correspondents=correspondents,
            document_types=document_types,
            tags=visible_tags,
            inbox_tag_id=inbox_tag.id,
        )

    async def ensure_family_group(self) -> int:
        groups = await self.list_objects("api/groups/", TaxonomyItem)
        existing = find_item(groups, FAMILY_GROUP_NAME)
        if existing is not None:
            return existing.id
        data = await self.request(
            "POST",
            "api/groups/",
            json_body={"name": FAMILY_GROUP_NAME, "permissions": []},
        )
        return TaxonomyItem.model_validate(data).id

    async def create_taxonomy_item(self, path: str, name: str) -> TaxonomyItem:
        group_id = await self.ensure_family_group()
        data = await self.request(
            "POST",
            f"api/{path}/",
            json_body={
                "name": name,
                "match": "",
                "matching_algorithm": 0,
                "is_insensitive": True,
                "set_permissions": family_permissions(group_id),
            },
        )
        return TaxonomyItem.model_validate(data)

    async def create_tag(self, name: str, *, is_inbox: bool = False) -> TaxonomyItem:
        group_id = await self.ensure_family_group()
        data = await self.request(
            "POST",
            "api/tags/",
            json_body={
                "name": name,
                "color": DEFAULT_TAG_COLOR,
                "is_inbox_tag": is_inbox,
                "match": "",
                "matching_algorithm": 0,
                "is_insensitive": True,
                "set_permissions": family_permissions(group_id),
            },
        )
        return TaxonomyItem.model_validate(data)

    async def update_document(
        self,
        document_id: int,
        *,
        title: str,
        correspondent_id: int,
        document_type_id: int,
        tag_ids: Sequence[int],
    ) -> None:
        await self.request(
            "PATCH",
            f"api/documents/{document_id}/",
            json_body={
                "title": title,
                "correspondent": correspondent_id,
                "document_type": document_type_id,
                "tags": list(tag_ids),
            },
        )


class ClassificationClient(Protocol):
    async def get_document(self, document_id: int) -> PaperlessDocument: ...

    async def create_taxonomy_item(self, path: str, name: str) -> TaxonomyItem: ...

    async def create_tag(
        self, name: str, *, is_inbox: bool = False
    ) -> TaxonomyItem: ...

    async def update_document(
        self,
        document_id: int,
        *,
        title: str,
        correspondent_id: int,
        document_type_id: int,
        tag_ids: Sequence[int],
    ) -> None: ...


def required_environment(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    raise RuntimeError(f"required environment variable is unset: {name}")


def normalize_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("Paperless URL must use HTTP or HTTPS and include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Paperless URL must not include credentials")
    return f"{value.rstrip('/')}/"


def normalize_page_url(value: str, *, expected_host: str) -> str:
    parsed = urlsplit(value)
    if parsed.hostname is not None and parsed.hostname != expected_host:
        raise ValueError(
            f"Paperless pagination URL has unexpected host: {parsed.hostname}"
        )
    path = parsed.path.lstrip("/")
    return f"{path}?{parsed.query}" if parsed.query else path


def parse_page(data: object) -> tuple[list[object], str | None]:
    if isinstance(data, list):
        return data, None
    if not isinstance(data, dict):
        raise TypeError("Paperless returned an invalid collection response")
    results = data.get("results")
    if not isinstance(results, list):
        raise TypeError("Paperless collection response has no results list")
    next_url = data.get("next")
    if next_url is not None and not isinstance(next_url, str):
        raise ValueError("Paperless collection response has an invalid next URL")
    return results, next_url


def family_permissions(group_id: int) -> dict[str, object]:
    principals = {"users": [], "groups": [group_id]}
    return {"view": principals, "change": principals}


def normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def find_item(items: Sequence[TaxonomyItem], name: str) -> TaxonomyItem | None:
    normalized_name = normalize_name(name)
    return next(
        (item for item in items if normalize_name(item.name) == normalized_name),
        None,
    )


def sanitize_content(text: str) -> str:
    text = ftfy.fix_text(text)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]", "", text)
    text = re.sub(r"[_\.]{5,}", "", text)
    text = re.sub(r"[-=~*]{5,}", "", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def new_names(names: Sequence[str], existing: Sequence[TaxonomyItem]) -> set[str]:
    existing_names = {normalize_name(item.name) for item in existing}
    return {normalize_name(name) for name in names} - existing_names


def validate_batch(
    batch: ClassificationBatch,
    expected_document_ids: set[int] | frozenset[int],
    taxonomy: Taxonomy,
    *,
    allow_deferred: bool,
) -> ClassificationBatch:
    document_ids = [decision.document_id for decision in batch.decisions]
    duplicate_ids = sorted(
        document_id
        for document_id in set(document_ids)
        if document_ids.count(document_id) > 1
    )
    if duplicate_ids:
        duplicates = ", ".join(str(document_id) for document_id in duplicate_ids)
        raise ValueError(f"duplicate document IDs: {duplicates}")

    actual_ids = set(document_ids)
    missing_ids = sorted(expected_document_ids - actual_ids)
    unexpected_ids = sorted(actual_ids - expected_document_ids)
    if missing_ids or unexpected_ids:
        raise ValueError(
            f"missing document IDs: {missing_ids}; unexpected document IDs: {unexpected_ids}"
        )

    deferred = [
        decision
        for decision in batch.decisions
        if isinstance(decision, DeferredClassification)
    ]
    if deferred and not allow_deferred:
        raise ValueError("full-content documents must be classified, not deferred")

    classifications = [
        decision for decision in batch.decisions if isinstance(decision, Classification)
    ]
    validate_taxonomy_growth(classifications, taxonomy)
    return batch


def validate_taxonomy_growth(
    classifications: Sequence[Classification], taxonomy: Taxonomy
) -> None:
    proposed_types = [item.document_type for item in classifications]
    added_types = new_names(proposed_types, taxonomy.document_types)
    if len(taxonomy.document_types) + len(added_types) > DOCUMENT_TYPE_LIMIT:
        raise ValueError("proposed document types exceed the document type cap")

    proposed_tags = [tag for item in classifications for tag in item.tags]
    added_tags = new_names(proposed_tags, taxonomy.tags)
    if len(taxonomy.tags) + len(added_tags) > TAG_LIMIT:
        raise ValueError("proposed tags exceed the tag cap")

    existing_tags = {normalize_name(item.name) for item in taxonomy.tags}
    new_tag_values = {
        tag for tag in proposed_tags if normalize_name(tag) not in existing_tags
    }
    invalid_tags = sorted(
        tag
        for tag in new_tag_values
        if tag != normalize_name(tag) or not is_valid_tag_name(tag)
    )
    if invalid_tags:
        raise ValueError(
            f"new tags must be lowercase words or hyphenated phrases: {invalid_tags}"
        )

    invalid_types = sorted(name for name in added_types if len(name.split()) > 3)
    if invalid_types:
        raise ValueError(
            f"new document types must contain at most three words: {invalid_types}"
        )


def is_valid_tag_name(name: str) -> bool:
    return re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) is not None


def build_agent(
    model_name: str,
    api_key: str,
    http_client: httpx.AsyncClient,
) -> Agent[ValidationContext, ClassificationBatch]:
    provider = DeepSeekProvider(api_key=api_key, http_client=http_client)
    model = OpenAIChatModel(model_name, provider=provider)
    agent = Agent[ValidationContext, ClassificationBatch](
        model,
        deps_type=ValidationContext,
        output_type=ClassificationBatch,
        instructions=CLASSIFIER_INSTRUCTIONS,
        model_settings=ModelSettings(
            temperature=0,
            max_tokens=8_000,
            thinking=False,
            parallel_tool_calls=False,
        ),
        retries={"output": 2},
    )

    @agent.output_validator
    def validate_output(
        context: RunContext[ValidationContext],
        output: ClassificationBatch,
    ) -> ClassificationBatch:
        try:
            return validate_batch(
                output,
                context.deps.expected_document_ids,
                context.deps.taxonomy,
                allow_deferred=context.deps.allow_deferred,
            )
        except ValueError as error:
            raise ModelRetry(str(error)) from error

    return agent


CLASSIFIER_INSTRUCTIONS = """
Classify every supplied Paperless-ngx document using the supplied taxonomy.

For each document, return exactly one decision. Use needs_full_content only when the compact OCR
excerpt genuinely lacks enough information. A full-content document must receive a classification.

Every classification requires a correspondent, document type, one or more tags, and a concise
title. Reuse taxonomy names exactly when they fit. Create a correspondent name only for an external
issuer not already represented, normalizing subsidiaries to a recognizable parent brand. Document
types describe the form, not the topic, and contain at most three words. Tags describe broad
domains, use lowercase words or short hyphenated phrases, and do not duplicate the correspondent or
document type. Never invent a single-use tag. Titles use "Description (Date or Context)" and never
repeat the correspondent name.

Evaluate all fields independently because existing Paperless assignments may be wrong.
""".strip()


def taxonomy_payload(taxonomy: Taxonomy) -> dict[str, list[dict[str, object]]]:
    return {
        "correspondents": [item.model_dump() for item in taxonomy.correspondents],
        "document_types": [item.model_dump() for item in taxonomy.document_types],
        "tags": [item.model_dump() for item in taxonomy.tags],
    }


def document_payload(
    document: PaperlessDocument,
    taxonomy: Taxonomy,
    *,
    content_limit: int,
) -> dict[str, object]:
    correspondents = {item.id: item.name for item in taxonomy.correspondents}
    document_types = {item.id: item.name for item in taxonomy.document_types}
    tags = {item.id: item.name for item in taxonomy.tags}
    content = sanitize_content(document.content)
    current_correspondent = (
        correspondents.get(document.correspondent)
        if document.correspondent is not None
        else None
    )
    current_document_type = (
        document_types.get(document.document_type)
        if document.document_type is not None
        else None
    )
    return {
        "id": document.id,
        "title": document.title,
        "created": document.created,
        "current_correspondent": current_correspondent,
        "current_document_type": current_document_type,
        "current_tags": [
            tags[tag_id]
            for tag_id in document.tags
            if tag_id != taxonomy.inbox_tag_id and tag_id in tags
        ],
        "content": content[:content_limit],
        "content_length": len(content),
        "content_truncated": len(content) > content_limit,
    }


def classification_prompt(
    documents: Sequence[PaperlessDocument],
    taxonomy: Taxonomy,
    *,
    content_limit: int,
) -> str:
    payload = {
        "taxonomy": taxonomy_payload(taxonomy),
        "documents": [
            document_payload(document, taxonomy, content_limit=content_limit)
            for document in documents
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


async def classify_documents(
    documents: Sequence[PaperlessDocument],
    taxonomy: Taxonomy,
    agent: Agent[ValidationContext, ClassificationBatch],
) -> tuple[Classification, ...]:
    first_pass = await run_classification_pass(
        documents,
        taxonomy,
        agent,
        content_limit=COMPACT_CONTENT_LIMIT,
        allow_deferred=True,
    )
    classifications = {
        decision.document_id: decision
        for decision in first_pass.decisions
        if isinstance(decision, Classification)
    }
    deferred_ids = {
        decision.document_id
        for decision in first_pass.decisions
        if isinstance(decision, DeferredClassification)
    }
    if deferred_ids:
        full_documents = [item for item in documents if item.id in deferred_ids]
        second_pass = await run_classification_pass(
            full_documents,
            taxonomy,
            agent,
            content_limit=FULL_CONTENT_LIMIT,
            allow_deferred=False,
        )
        classifications.update(
            {
                decision.document_id: decision
                for decision in second_pass.decisions
                if isinstance(decision, Classification)
            }
        )
    ordered = tuple(classifications[document.id] for document in documents)
    validate_taxonomy_growth(ordered, taxonomy)
    return ordered


async def run_classification_pass(
    documents: Sequence[PaperlessDocument],
    taxonomy: Taxonomy,
    agent: Agent[ValidationContext, ClassificationBatch],
    *,
    content_limit: int,
    allow_deferred: bool,
) -> ClassificationBatch:
    document_ids = frozenset(document.id for document in documents)
    result = await agent.run(
        classification_prompt(documents, taxonomy, content_limit=content_limit),
        deps=ValidationContext(document_ids, taxonomy, allow_deferred),
        usage_limits=UsageLimits(request_limit=3, output_tokens_limit=12_000),
    )
    LOGGER.info(
        "model classified %d documents with %d request(s)",
        len(documents),
        result.usage.requests,
    )
    return result.output


async def ensure_named_item(
    client: ClassificationClient,
    items: list[TaxonomyItem],
    path: str,
    name: str,
) -> TaxonomyItem:
    existing = find_item(items, name)
    if existing is not None:
        return existing
    if path == "tags":
        created = await client.create_tag(name)
    else:
        created = await client.create_taxonomy_item(path, name)
    items.append(created)
    LOGGER.info("created %s #%d: %s", path.rstrip("s"), created.id, created.name)
    return created


async def apply_classifications(
    client: ClassificationClient,
    classifications: Sequence[Classification],
    taxonomy: Taxonomy,
) -> tuple[int, int]:
    correspondents = list(taxonomy.correspondents)
    document_types = list(taxonomy.document_types)
    tags = list(taxonomy.tags)
    updated = 0
    stale = 0

    for classification in classifications:
        current = await client.get_document(classification.document_id)
        if taxonomy.inbox_tag_id not in current.tags:
            LOGGER.warning(
                "skipping document #%d because it left the inbox",
                classification.document_id,
            )
            stale += 1
            continue

        correspondent = await ensure_named_item(
            client,
            correspondents,
            "correspondents",
            classification.correspondent,
        )
        document_type = await ensure_named_item(
            client,
            document_types,
            "document_types",
            classification.document_type,
        )
        resolved_tags = [
            await ensure_named_item(client, tags, "tags", tag)
            for tag in classification.tags
        ]
        await client.update_document(
            classification.document_id,
            title=classification.title,
            correspondent_id=correspondent.id,
            document_type_id=document_type.id,
            tag_ids=sorted({tag.id for tag in resolved_tags}),
        )
        updated += 1
        LOGGER.info("classified document #%d: %s", current.id, classification.title)

    return updated, stale


async def run() -> int:
    settings = Settings.from_environment()
    model_http_client = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10))
    try:
        agent = build_agent(
            settings.deepseek_model,
            settings.deepseek_api_key,
            model_http_client,
        )
        async with PaperlessClient(
            settings.paperless_url,
            settings.paperless_token,
        ) as paperless:
            taxonomy = await paperless.load_taxonomy()
            documents = await paperless.list_inbox_documents()
            if not documents:
                LOGGER.info("no documents to classify")
                return 0

            LOGGER.info("classifying %d document(s)", len(documents))
            classifications = await classify_documents(documents, taxonomy, agent)
            updated, stale = await apply_classifications(
                paperless,
                classifications,
                taxonomy,
            )
            LOGGER.info("classification complete: %d updated, %d stale", updated, stale)
            return 0
    finally:
        await model_http_client.aclose()


def main() -> int:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
    )
    with TRACER.start_as_current_span("paperless.classify") as span:
        try:
            result = asyncio.run(run())
        except (httpx.HTTPError, TypeError, ValueError, RuntimeError) as error:
            span.set_attribute("classification.outcome", "failed")
            span.set_attribute("exception.type", type(error).__name__)
            span.set_status(Status(StatusCode.ERROR, type(error).__name__))
            LOGGER.error("classification failed: %s", error)
            return 1
        except Exception as error:
            span.set_attribute("classification.outcome", "failed")
            span.set_attribute("exception.type", type(error).__name__)
            span.set_status(Status(StatusCode.ERROR, type(error).__name__))
            LOGGER.exception("classification failed unexpectedly")
            return 1
        span.set_attribute("classification.outcome", "success")
        return result


if __name__ == "__main__":
    sys.exit(main())
