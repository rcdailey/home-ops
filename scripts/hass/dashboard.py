"""Inspect Lovelace dashboards, cards, and resources."""

from __future__ import annotations

import json

import click

from hass._client import die, run_ws, ws_error


def _collect_cards(view: dict) -> list[dict]:
    """Recursively collect all cards from a view, flattening nested stacks."""
    cards: list[dict] = []
    for card in view.get("cards", []):
        cards.append(card)
        if card.get("type") in (
            "vertical-stack",
            "horizontal-stack",
            "grid",
            "custom:layout-card",
        ):
            cards.extend(_collect_cards(card))
        for section in card.get("sections", []):
            cards.extend(_collect_cards(section))
    for section in view.get("sections", []):
        cards.extend(_collect_cards(section))
    return cards


@click.group()
def cli() -> None:
    """Inspect Lovelace dashboards."""


@cli.command("list")
def list_cmd() -> None:
    """List all dashboards."""

    async def handler(send):
        msg = await send({"type": "lovelace/dashboards/list"})
        dashboards = msg.get("result", [])
        click.echo(f"  {'URL Path':20s} {'Title':25s} {'Mode':10s}")
        click.echo(f"  {'-' * 20} {'-' * 25} {'-' * 10}")
        click.echo(f"  {'(default)':20s} {'Overview':25s} {'storage':10s}")
        for d in sorted(dashboards, key=lambda x: x.get("url_path", "")):
            url = d.get("url_path", "")
            title = d.get("title", "(untitled)")
            mode = d.get("mode", "?")
            click.echo(f"  {url:20s} {title:25s} {mode:10s}")

    run_ws(handler)


@cli.command("resources")
def resources_cmd() -> None:
    """List Lovelace resources (JS/CSS)."""

    async def handler(send):
        msg = await send({"type": "lovelace/resources"})
        resources = msg.get("result", [])
        if not resources:
            click.echo("(no lovelace resources)")
            return
        for r in resources:
            rtype = r.get("type", "?")
            url = r.get("url", "")
            click.echo(f"  [{rtype:6s}] {url}")

    run_ws(handler)


@cli.command("get")
@click.argument("url_path", required=False)
def get_cmd(url_path: str | None) -> None:
    """Dump full config for a dashboard (default: Overview)."""

    async def handler(send):
        payload: dict = {"type": "lovelace/config"}
        if url_path:
            payload["url_path"] = url_path
        msg = await send(payload)
        if not msg.get("success"):
            die(f"Error: {ws_error(msg)}")
        click.echo(json.dumps(msg["result"], indent=2))

    run_ws(handler)


@cli.command("cards")
@click.argument("url_path", required=False)
@click.option("--type", "type_filter", help="Filter cards by type substring")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def cards_cmd(url_path: str | None, type_filter: str | None, as_json: bool) -> None:
    """Summarize cards in a dashboard."""

    async def handler(send):
        payload: dict = {"type": "lovelace/config"}
        if url_path:
            payload["url_path"] = url_path
        msg = await send(payload)
        if not msg.get("success"):
            die(f"Error: {ws_error(msg)}")
        config = msg["result"]

        all_cards = []
        for view in config.get("views", []):
            view_title = view.get("title", view.get("path", "(untitled)"))
            for card in _collect_cards(view):
                card_type = card.get("type", "?")
                if type_filter and type_filter not in card_type:
                    continue
                entity = card.get("entity", "")
                name = card.get("name", card.get("title", ""))
                all_cards.append(
                    {
                        "view": view_title,
                        "type": card_type,
                        "name": name,
                        "entity": entity,
                        "config": card,
                    }
                )

        if not all_cards:
            label = f" matching '{type_filter}'" if type_filter else ""
            click.echo(f"(no cards{label})")
            return

        if as_json:
            click.echo(json.dumps([c["config"] for c in all_cards], indent=2))
            return

        for c in all_cards:
            parts = [c["type"]]
            if c["name"]:
                parts.append(c["name"])
            if c["entity"]:
                parts.append(c["entity"])
            click.echo(f"  [{c['view']}] {' | '.join(parts)}")

    run_ws(handler)
