"""Tests for doc commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from paperless.cli import cli


def _mock_doc(doc_id: int = 1, title: str = "Test Doc"):
    doc = MagicMock()
    doc.id = doc_id
    doc.title = title
    doc.correspondent = None
    doc.document_type = None
    doc.tags = []
    doc.created = "2024-01-15"
    doc.added = "2024-01-15"
    doc.archive_serial_number = None
    doc.storage_path = None
    doc.custom_fields = []
    doc.content = "test content"
    return doc


def _make_client():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def test_doc_show():
    doc = _mock_doc(42, "Invoice 2024")
    client = _make_client()
    client.documents = AsyncMock(return_value=doc)
    client.tags = AsyncMock()
    client.correspondents = AsyncMock()
    client.document_types = AsyncMock()

    with patch("paperless.doc.commands.open_client", return_value=client):
        runner = CliRunner()
        result = runner.invoke(cli, ["doc", "show", "42"])
        assert result.exit_code == 0
        assert "Invoice 2024" in result.output
        assert "#42" in result.output


def test_doc_search_no_results():
    client = _make_client()

    async def _empty_search(query):
        return
        yield

    client.documents.search = _empty_search

    with patch("paperless.doc.commands.open_client", return_value=client):
        runner = CliRunner()
        result = runner.invoke(cli, ["doc", "search", "nonexistent"])
        assert result.exit_code == 0
        assert "no results" in result.output
