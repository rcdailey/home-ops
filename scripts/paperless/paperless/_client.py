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
    """Run an async coroutine synchronously, reporting API failures cleanly."""
    from httpx import HTTPStatusError, TransportError
    from pypaperless.exceptions import PaperlessError

    url = get_url()
    try:
        return asyncio.run(coro)
    except HTTPStatusError as exc:
        die(
            f"{exc.response.status_code} {exc.response.reason_phrase}: "
            f"{exc.request.url}"
        )
    except TransportError as exc:
        die(f"cannot reach {url}: {exc}")
    except PaperlessError as exc:
        # pypaperless raises some of these with no args, which would otherwise
        # print a bare "error:" with nothing to act on.
        die(str(exc) or f"{type(exc).__name__} from {url}")
    except Exception as exc:
        # Last-resort boundary: any other failure from the async stack becomes
        # a one-line CLI error instead of a traceback. Mirrors die().
        raise SystemExit(
            f"error: unexpected error talking to {url}: {type(exc).__name__}: {exc}"
        ) from exc


def open_client():
    """Create a PaperlessClient (use as async context manager)."""
    from pypaperless import PaperlessClient

    return PaperlessClient(get_url(), get_token())


def get_transport():
    """Return a raw PaperlessTransport for direct API calls."""
    from pypaperless.transport import PaperlessTransport

    return PaperlessTransport(get_url(), get_token())
