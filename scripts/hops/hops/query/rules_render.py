"""Rendering for vmalert rule inventory."""

from __future__ import annotations

from typing import Any

import click

from hops.core.format import age_str, info, kv, table, truncate
from hops.query._vm import is_ignored_alert

SLOW_EVAL_SECONDS = 1.0


def flatten(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten the group/rule nesting, carrying group context onto each rule."""
    return [
        {**rule, "group": group.get("name", "?"), "interval": group.get("interval")}
        for group in groups
        for rule in group.get("rules", [])
    ]


def is_broken(rule: dict[str, Any]) -> bool:
    return rule.get("health", "ok") != "ok" or bool(rule.get("lastError"))


def render(rules: list[dict[str, Any]], show_all: bool) -> None:
    """Report rule health, defaulting to problems only.

    A full dump of every rule is mostly inactive noise. The questions worth
    asking are which rules fail to evaluate (the cause behind
    AlertingRulesError/RecordingRulesError), which are firing or pending, and
    which are slow enough to fall behind their group interval.
    """
    if not rules:
        info("No alert rules found")
        return

    _summary(rules)

    broken = [r for r in rules if is_broken(r)]
    if broken:
        click.echo("\nUnhealthy rules:")
        table(
            ["RULE", "GROUP", "HEALTH", "ERROR"],
            [
                [
                    r.get("name", "?"),
                    r.get("group", "?"),
                    r.get("health", "?"),
                    truncate(r.get("lastError", ""), 90),
                ]
                for r in broken
            ],
        )

    active = [
        r
        for r in rules
        if r.get("state") in ("firing", "pending")
        and not is_ignored_alert(r.get("name", ""))
    ]
    if active:
        click.echo("\nActive rules:")
        table(
            ["RULE", "GROUP", "STATE", "SEVERITY", "LAST EVAL"],
            [
                [
                    r.get("name", "?"),
                    r.get("group", "?"),
                    r.get("state", "?"),
                    r.get("labels", {}).get("severity", "none"),
                    age_str(r.get("lastEvaluation")),
                ]
                for r in sorted(active, key=lambda r: r.get("state", ""))
            ],
        )

    slow = sorted(
        (r for r in rules if float(r.get("evaluationTime") or 0) >= SLOW_EVAL_SECONDS),
        key=lambda r: float(r.get("evaluationTime") or 0),
        reverse=True,
    )
    if slow:
        click.echo(f"\nSlow rules (>={SLOW_EVAL_SECONDS:g}s per evaluation):")
        table(
            ["RULE", "GROUP", "EVAL", "INTERVAL"],
            [
                [
                    r.get("name", "?"),
                    r.get("group", "?"),
                    f"{float(r.get('evaluationTime') or 0):.2f}s",
                    f"{r.get('interval', '?')}s",
                ]
                for r in slow[:15]
            ],
        )

    if not show_all:
        if not (broken or active or slow):
            click.echo("\nAll rules healthy and inactive")
        return

    click.echo("\nAll rules:")
    table(
        ["RULE", "GROUP", "TYPE", "STATE"],
        [
            [
                r.get("name", "?"),
                r.get("group", "?"),
                r.get("type", "?"),
                r.get("state") or "-",
            ]
            for r in rules
        ],
    )


def _summary(rules: list[dict[str, Any]]) -> None:
    states: dict[str, int] = {}
    for rule in rules:
        # Recording rules carry no state; count them by type instead so the
        # totals add up to the rule count.
        key = rule.get("state") or rule.get("type", "recording")
        states[key] = states.get(key, 0) + 1
    pairs = [
        ("Rules", str(len(rules))),
        ("Groups", str(len({r.get("group") for r in rules}))),
        ("States", ", ".join(f"{k}={v}" for k, v in sorted(states.items()))),
        ("Unhealthy", str(sum(1 for r in rules if is_broken(r)))),
    ]
    # Named so the state totals above reconcile with the shorter active table.
    suppressed = sum(
        1
        for r in rules
        if r.get("state") in ("firing", "pending")
        and is_ignored_alert(r.get("name", ""))
    )
    if suppressed:
        pairs.append(("Suppressed", f"{suppressed} (always-on/ignored alerts)"))
    kv(pairs)
