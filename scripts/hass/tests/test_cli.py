"""Tests for the root CLI group and basic command discovery."""

from __future__ import annotations

from click.testing import CliRunner

from hass.cli import cli


def test_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Home Assistant API wrapper" in result.output


def test_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_commands_discovered():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "states" in result.output
    assert "history" in result.output
    assert "trigger" in result.output
