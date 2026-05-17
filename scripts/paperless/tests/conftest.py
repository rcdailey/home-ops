"""Shared test fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set required env vars for all tests."""
    monkeypatch.setenv("PAPERLESS_URL", "http://localhost:8000")
    monkeypatch.setenv("PAPERLESS_TOKEN", "test-token")
