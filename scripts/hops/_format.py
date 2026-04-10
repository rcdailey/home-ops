"""Shared output formatting utilities."""

from __future__ import annotations

import sys
from typing import Sequence


def table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    """Print a fixed-width table with headers.

    Columns are space-separated, widths auto-calculated from content.
    No borders, no decorators. Designed for minimal token usage.
    """
    if not rows:
        return
    all_rows = [list(headers)] + [list(r) for r in rows]
    ncols = len(headers)
    widths = [0] * ncols
    for row in all_rows:
        for i, cell in enumerate(row[:ncols]):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt_row(row):
        parts = []
        for i, cell in enumerate(row[:ncols]):
            if i == ncols - 1:
                parts.append(str(cell))
            else:
                parts.append(str(cell).ljust(widths[i]))
        return "  ".join(parts)

    print(fmt_row(headers))
    for row in rows:
        print(fmt_row(row))


def kv(pairs: Sequence[tuple[str, str]], indent: int = 0) -> None:
    """Print key-value pairs, one per line.

    Aligns values to the longest key.
    """
    if not pairs:
        return
    prefix = " " * indent
    max_key = max(len(k) for k, _ in pairs)
    for key, value in pairs:
        print(f"{prefix}{key + ':':<{max_key + 1}} {value}")


def section(title: str) -> None:
    """Print a section header."""
    print(f"\n--- {title} ---")


def info(msg: str) -> None:
    """Print an informational message."""
    print(msg)


def error(msg: str) -> None:
    """Print an error message to stderr."""
    print(f"error: {msg}", file=sys.stderr)


def human_bytes(n: int | float) -> str:
    """Convert bytes to human-readable string (Ki, Mi, Gi, Ti)."""
    for unit in ("B", "Ki", "Mi", "Gi", "Ti", "Pi"):
        if abs(n) < 1024:
            if n == int(n):
                return f"{int(n)}{unit}"
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}Ei"


def human_size(size_str: str) -> str:
    """Normalize a Kubernetes size string (e.g., '1000000000' -> '1Gi')."""
    try:
        return human_bytes(int(size_str))
    except (ValueError, TypeError):
        return str(size_str)


def age(seconds: float) -> str:
    """Convert seconds to a human-readable age string."""
    if seconds < 0:
        return "future"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    if seconds < 86400:
        return f"{int(seconds / 3600)}h"
    return f"{int(seconds / 86400)}d"


def truncate(s: str, max_len: int = 120) -> str:
    """Truncate a string, appending ... if shortened."""
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."
