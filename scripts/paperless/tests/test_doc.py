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


async def _async_iter(items):
    for item in items:
        yield item


def test_tasks_shows_active():
    task = MagicMock()
    task.status = "started"
    client = _make_client()
    client.tasks = MagicMock()
    client.tasks.active = lambda: _async_iter([task, task])

    with patch("paperless.doc.commands.open_client", return_value=client):
        runner = CliRunner()
        result = runner.invoke(cli, ["doc", "tasks"])
        assert result.exit_code == 0
        assert "2 active" in result.output
        assert "started" in result.output


def test_tasks_no_active():
    client = _make_client()
    client.tasks = MagicMock()
    client.tasks.active = lambda: _async_iter([])

    with patch("paperless.doc.commands.open_client", return_value=client):
        runner = CliRunner()
        result = runner.invoke(cli, ["doc", "tasks"])
        assert result.exit_code == 0
        assert "no active tasks" in result.output


def test_upload_single_file(tmp_path):
    pdf = tmp_path / "invoice.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")

    client = _make_client()
    client.documents.create = MagicMock(return_value=MagicMock())
    client.documents.save = AsyncMock(return_value="task-abc")

    with patch("paperless.doc.commands.open_client", return_value=client):
        runner = CliRunner()
        result = runner.invoke(cli, ["doc", "upload", str(pdf)])
        assert result.exit_code == 0
        assert "uploaded invoice.pdf" in result.output
        assert "task: task-abc" in result.output


def test_upload_directory(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    (tmp_path / "b.pdf").write_bytes(b"%PDF")
    (tmp_path / "c.txt").write_bytes(b"not a pdf")

    client = _make_client()
    client.documents.create = MagicMock(return_value=MagicMock())
    client.documents.save = AsyncMock(return_value="task-123")

    with patch("paperless.doc.commands.open_client", return_value=client):
        runner = CliRunner()
        result = runner.invoke(cli, ["doc", "upload", str(tmp_path)])
        assert result.exit_code == 0
        assert "uploading 2 file(s)" in result.output
        assert "uploaded a.pdf" in result.output
        assert "uploaded b.pdf" in result.output
        assert "c.txt" not in result.output


def test_upload_directory_recursive(tmp_path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    (tmp_path / "top.pdf").write_bytes(b"%PDF")
    (sub / "nested.pdf").write_bytes(b"%PDF")

    client = _make_client()
    client.documents.create = MagicMock(return_value=MagicMock())
    client.documents.save = AsyncMock(return_value="task-456")

    with patch("paperless.doc.commands.open_client", return_value=client):
        runner = CliRunner()
        result = runner.invoke(cli, ["doc", "upload", "-r", str(tmp_path)])
        assert result.exit_code == 0
        assert "uploading 2 file(s)" in result.output
        assert "uploaded nested.pdf" in result.output
        assert "uploaded top.pdf" in result.output


def test_upload_directory_no_recursive_skips_nested(tmp_path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    (tmp_path / "top.pdf").write_bytes(b"%PDF")
    (sub / "nested.pdf").write_bytes(b"%PDF")

    client = _make_client()
    client.documents.create = MagicMock(return_value=MagicMock())
    client.documents.save = AsyncMock(return_value="task-789")

    with patch("paperless.doc.commands.open_client", return_value=client):
        runner = CliRunner()
        result = runner.invoke(cli, ["doc", "upload", str(tmp_path)])
        assert result.exit_code == 0
        assert "uploading 1 file(s)" in result.output
        assert "uploaded top.pdf" in result.output
        assert "nested.pdf" not in result.output


def test_upload_directory_with_title_errors(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF")

    runner = CliRunner()
    result = runner.invoke(cli, ["doc", "upload", "--title", "Bad", str(tmp_path)])
    assert result.exit_code == 1
    assert "--title cannot be used with directory uploads" in result.output


def test_upload_empty_directory_errors(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["doc", "upload", str(tmp_path)])
    assert result.exit_code == 1
    assert "no PDF files found" in result.output
