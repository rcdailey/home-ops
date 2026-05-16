"""Tests for error handling utilities."""

from __future__ import annotations

import pytest

from hass._errors import HassError, die


def test_die_exits(capsys):
    with pytest.raises(SystemExit) as exc_info:
        die("something broke")
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "error: something broke" in captured.err


def test_hass_error_is_exception():
    with pytest.raises(HassError):
        raise HassError("test failure")
