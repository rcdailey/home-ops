"""Tests for config command."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from paperless.cli import cli


def test_config_missing_env(monkeypatch):
    monkeypatch.delenv("PAPERLESS_URL", raising=False)
    monkeypatch.delenv("PAPERLESS_TOKEN", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["config"])
    assert result.exit_code != 0


def test_config_status_success():
    stats = MagicMock()
    stats.documents_total = 42
    stats.documents_inbox = 5

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.statistics = AsyncMock(return_value=stats)

    with patch("paperless.config.open_client", return_value=mock_client):
        runner = CliRunner()
        result = runner.invoke(cli, ["config"])
        assert result.exit_code == 0
        assert "connected to" in result.output
        assert "42" in result.output
