"""Shared OpenTelemetry scrape-target health inspection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from hops.query._vm import query_vm


def active_target_health(
    namespace: str | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Return active target count and targets whose latest scrape failed."""
    data = query_vm("/api/v1/query", {"query": "up"})
    targets = []
    for result in data.get("data", {}).get("result", []):
        labels = result.get("metric", {})
        value = result.get("value", [0, "0"])
        targets.append(
            {
                "labels": labels,
                "health": "up" if value[1] == "1" else "down",
                "lastScrape": datetime.fromtimestamp(float(value[0]), UTC).isoformat(),
                "lastError": "up metric is zero" if value[1] != "1" else "",
                "scrapePool": labels.get("job", "?"),
            }
        )
    if namespace:
        targets = [
            target
            for target in targets
            if target.get("labels", {}).get("namespace") == namespace
        ]
    unhealthy = [target for target in targets if target.get("health") != "up"]
    return len(targets), unhealthy


def target_identity(target: dict[str, Any]) -> str:
    """Return the most useful compact identity for a scrape target."""
    labels = target.get("labels", {})
    return labels.get("pod") or labels.get("instance") or target.get("scrapeUrl", "?")
