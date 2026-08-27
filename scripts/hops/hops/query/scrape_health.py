"""Shared VMAgent scrape-target health inspection."""

from __future__ import annotations

from typing import Any

from hops.query._vm import query_vmagent


def active_target_health(
    namespace: str | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Return active target count and targets whose latest scrape failed."""
    data = query_vmagent("/api/v1/targets?state=active")
    targets = data.get("data", {}).get("activeTargets", [])
    if namespace:
        targets = [
            target
            for target in targets
            if target.get("labels", {}).get("namespace") == namespace
        ]
    unhealthy = [
        target
        for target in targets
        if target.get("health") != "up" or target.get("lastError")
    ]
    return len(targets), unhealthy


def target_identity(target: dict[str, Any]) -> str:
    """Return the most useful compact identity for a scrape target."""
    labels = target.get("labels", {})
    return labels.get("pod") or labels.get("instance") or target.get("scrapeUrl", "?")
