"""Async bridge for pypaperless client."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable
from typing import TypeVar

from paperless._errors import die

T = TypeVar("T")


def _require_env(name: str) -> str:
    """Return env var value or die with clear message."""
    value = os.environ.get(name)
    if not value:
        die(f"{name} is not set")
    return value


def get_url() -> str:
    """Return the Paperless instance URL."""
    return _require_env("PAPERLESS_URL").rstrip("/")


def get_token() -> str:
    """Return the Paperless API token."""
    return _require_env("PAPERLESS_TOKEN")


def run_async(coro: Awaitable[T]) -> T:
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def open_client():
    """Create a PaperlessClient (use as async context manager)."""
    from pypaperless import PaperlessClient

    return PaperlessClient(get_url(), get_token())
