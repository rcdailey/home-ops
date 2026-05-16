"""Error types and fatal exit helper."""

from __future__ import annotations

import sys
from typing import NoReturn


class HopsError(Exception):
    """Domain-specific error (e.g., kubectl failure, resolution failure)."""


def die(message: str) -> NoReturn:
    """Print error to stderr and exit."""
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)
