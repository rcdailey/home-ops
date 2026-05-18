"""Tests for classify commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from paperless.cli import cli


def _mock_doc(
    doc_id: int = 1,
    title: str = "Test Doc",
    content: str = "short content",
    tags: list[int] | None = None,
    correspondent: int | None = None,
    document_type: int | None = None,
):
    doc = MagicMock()
    doc.id = doc_id
    doc.title = title
    doc.content = content
    doc.tags = tags or [99]  # 99 = inbox tag
    doc.correspondent = correspondent
    doc.document_type = document_type
    doc.created = "2024-01-15"
    return doc


def _make_client():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _mock_tag(tag_id: int, name: str):
    t = MagicMock()
    t.id = tag_id
    t.name = name
    return t


def _mock_type(type_id: int, name: str):
    t = MagicMock()
    t.id = type_id
    t.name = name
    return t


def _mock_corr(corr_id: int, name: str):
    c = MagicMock()
    c.id = corr_id
    c.name = name
    return c


INBOX_TAG_ID = 99


def _async_iterable(*items):
    """Create a mock that works as an async iterable."""
    mock = AsyncMock()

    async def _aiter(self=None):
        for item in items:
            yield item

    mock.__aiter__ = _aiter
    return mock


# --- brief tests ---


def test_brief_compact_truncates_at_500():
    long_content = "x" * 1000
    doc = _mock_doc(1, "Test", content=long_content)
    client = _make_client()
    client.documents = _async_iterable(doc)
    client.tags.as_list = AsyncMock(
        return_value=[_mock_tag(INBOX_TAG_ID, "inbox"), _mock_tag(3, "home")]
    )
    client.document_types.as_list = AsyncMock(return_value=[_mock_type(1, "Receipt")])
    client.correspondents.as_list = AsyncMock(return_value=[])

    with (
        patch("paperless.classify.commands.open_client", return_value=client),
        patch(
            "paperless.classify.commands.ensure_inbox_tag", return_value=INBOX_TAG_ID
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "brief"])
        assert result.exit_code == 0
        assert "[...truncated from 1000 chars]" in result.output
        # Compact mode: 500 x's, not 1000
        assert "x" * 501 not in result.output


def test_brief_full_truncates_at_2000():
    long_content = "y" * 3000
    doc = _mock_doc(1, "Test", content=long_content)
    client = _make_client()
    client.documents = _async_iterable(doc)
    client.tags.as_list = AsyncMock(return_value=[_mock_tag(INBOX_TAG_ID, "inbox")])
    client.document_types.as_list = AsyncMock(return_value=[])
    client.correspondents.as_list = AsyncMock(return_value=[])

    with (
        patch("paperless.classify.commands.open_client", return_value=client),
        patch(
            "paperless.classify.commands.ensure_inbox_tag", return_value=INBOX_TAG_ID
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "brief", "--full"])
        assert result.exit_code == 0
        assert "[...truncated from 3000 chars]" in result.output
        # Full mode: should have 2000 y's
        assert "y" * 2000 in result.output
        assert "y" * 2001 not in result.output


def test_brief_full_shows_keywords_for_long_docs():
    long_content = "The quick brown fox jumped over the lazy dog. " * 200
    doc = _mock_doc(1, "Test", content=long_content)
    client = _make_client()
    client.documents = _async_iterable(doc)
    client.tags.as_list = AsyncMock(return_value=[_mock_tag(INBOX_TAG_ID, "inbox")])
    client.document_types.as_list = AsyncMock(return_value=[])
    client.correspondents.as_list = AsyncMock(return_value=[])

    with (
        patch("paperless.classify.commands.open_client", return_value=client),
        patch(
            "paperless.classify.commands.ensure_inbox_tag", return_value=INBOX_TAG_ID
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "brief", "--full"])
        assert result.exit_code == 0
        assert "Keywords:" in result.output


def test_brief_compact_skips_keywords():
    long_content = "The quick brown fox jumped over the lazy dog. " * 200
    doc = _mock_doc(1, "Test", content=long_content)
    client = _make_client()
    client.documents = _async_iterable(doc)
    client.tags.as_list = AsyncMock(return_value=[_mock_tag(INBOX_TAG_ID, "inbox")])
    client.document_types.as_list = AsyncMock(return_value=[])
    client.correspondents.as_list = AsyncMock(return_value=[])

    with (
        patch("paperless.classify.commands.open_client", return_value=client),
        patch(
            "paperless.classify.commands.ensure_inbox_tag", return_value=INBOX_TAG_ID
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "brief"])
        assert result.exit_code == 0
        assert "Keywords:" not in result.output


# --- apply tests ---


def test_apply_classifies_documents():
    doc1 = _mock_doc(10, "Old Title 1")
    doc2 = _mock_doc(20, "Old Title 2")
    client = _make_client()

    async def _get_doc(doc_id):
        if doc_id == 10:
            return doc1
        return doc2

    client.documents = AsyncMock(side_effect=_get_doc)
    client.documents.update = AsyncMock()

    stdin_data = "10|5|7|3,4|New Title One\n20|6|7|3|New Title Two\n"

    with (
        patch("paperless.classify.commands.open_client", return_value=client),
        patch(
            "paperless.classify.commands.ensure_inbox_tag", return_value=INBOX_TAG_ID
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "apply"], input=stdin_data)
        assert result.exit_code == 0
        assert "#10: New Title One" in result.output
        assert "#20: New Title Two" in result.output
        assert "2/2 classified" in result.output

    assert doc1.title == "New Title One"
    assert doc1.correspondent == 5
    assert doc1.document_type == 7
    assert set(doc1.tags) == {3, 4}

    assert doc2.title == "New Title Two"
    assert doc2.correspondent == 6
    assert doc2.document_type == 7
    assert set(doc2.tags) == {3}


def test_apply_empty_correspondent():
    doc = _mock_doc(10, "Old Title", correspondent=5)
    client = _make_client()

    client.documents = AsyncMock(return_value=doc)
    client.documents.update = AsyncMock()

    stdin_data = "10||7|3|New Title\n"

    with (
        patch("paperless.classify.commands.open_client", return_value=client),
        patch(
            "paperless.classify.commands.ensure_inbox_tag", return_value=INBOX_TAG_ID
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "apply"], input=stdin_data)
        assert result.exit_code == 0
        assert "#10: New Title" in result.output

    # Correspondent should not be changed (empty field means skip)
    assert doc.correspondent == 5


def test_apply_removes_inbox_tag():
    doc = _mock_doc(10, "Old", tags=[INBOX_TAG_ID, 3])
    client = _make_client()

    client.documents = AsyncMock(return_value=doc)
    client.documents.update = AsyncMock()

    stdin_data = "10|5|7|3,4|New Title\n"

    with (
        patch("paperless.classify.commands.open_client", return_value=client),
        patch(
            "paperless.classify.commands.ensure_inbox_tag", return_value=INBOX_TAG_ID
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "apply"], input=stdin_data)
        assert result.exit_code == 0

    assert INBOX_TAG_ID not in doc.tags


def test_apply_skips_comments_and_blank_lines():
    doc = _mock_doc(10, "Old")
    client = _make_client()

    client.documents = AsyncMock(return_value=doc)
    client.documents.update = AsyncMock()

    stdin_data = "# This is a comment\n\n10|5|7|3|New Title\n\n"

    with (
        patch("paperless.classify.commands.open_client", return_value=client),
        patch(
            "paperless.classify.commands.ensure_inbox_tag", return_value=INBOX_TAG_ID
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "apply"], input=stdin_data)
        assert result.exit_code == 0
        assert "1/1 classified" in result.output


def test_apply_bad_format_exits():
    stdin_data = "10|5|7\n"  # Only 3 fields instead of 5

    runner = CliRunner()
    result = runner.invoke(cli, ["classify", "apply"], input=stdin_data)
    assert result.exit_code == 1
    assert "expected 5 pipe-delimited fields" in result.output


def test_apply_empty_stdin():
    with (
        patch("paperless.classify.commands.open_client"),
        patch(
            "paperless.classify.commands.ensure_inbox_tag", return_value=INBOX_TAG_ID
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(cli, ["classify", "apply"], input="")
        assert "no input lines" in result.output
