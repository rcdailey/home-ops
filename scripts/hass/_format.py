"""Shared formatting helpers."""

from __future__ import annotations

import click


def is_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def print_history_entry(entry: dict) -> None:
    """Print a single history entry with microseconds trimmed."""
    ts = entry.get("last_changed", "")
    if "." in ts:
        ts = (
            ts[: ts.index(".")] + ts[ts.index("+") :]
            if "+" in ts
            else ts[: ts.index(".")]
        )
    state = entry.get("state", "")
    click.echo(f"  {ts}  {state}")
