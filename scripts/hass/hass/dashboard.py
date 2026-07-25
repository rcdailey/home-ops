"""Inspect and mutate Lovelace dashboards, cards, and resources."""

from __future__ import annotations

import copy
import difflib
import json
from pathlib import Path

import click

from hass import _lovelace as lv
from hass._client import run_ws
from hass._errors import HassError, die


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
    """Inspect and edit Lovelace dashboards."""


@cli.command("list")
def list_cmd() -> None:
    """List all dashboards."""

    async def handler(send):
        msg = await send({"type": "lovelace/dashboards/list"})
        dashboards = msg.get("result", [])
        click.echo("(default) Overview mode=storage")
        for d in sorted(dashboards, key=lambda x: x.get("url_path", "")):
            title = d.get("title", "(untitled)")
            click.echo(f"{d.get('url_path', '')} {title} mode={d.get('mode', '?')}")

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
            click.echo(f"{r.get('type', '?')} {r.get('url', '')}")

    run_ws(handler)


@cli.command("views")
@click.argument("url_path", required=False)
def views_cmd(url_path: str | None) -> None:
    """List views and sections with the selectors accepted by other commands."""

    async def handler(send):
        config = await lv.fetch_config(send, url_path)
        for i, view in enumerate(config.get("views", [])):
            sections = view.get("sections", [])
            click.echo(
                f"{lv.view_label(view, i)} type={view.get('type', 'masonry')} "
                f"sections={len(sections)} cards={len(view.get('cards', []))}"
            )
            for j, section in enumerate(sections):
                title = lv.section_title(section) or "(untitled)"
                click.echo(f"  #{j} {title} cards={len(section.get('cards', []))}")

    _run(handler)


@cli.command("get")
@click.argument("url_path", required=False)
@click.option("--view", "view_sel", help="Narrow to one view (title, path, or #index)")
@click.option("--section", "section_sel", help="Narrow to one section within --view")
@click.option("--json", "as_json", is_flag=True, help="JSON instead of YAML")
def get_cmd(
    url_path: str | None,
    view_sel: str | None,
    section_sel: str | None,
    as_json: bool,
) -> None:
    """Dump dashboard config as YAML (default: Overview, all views)."""

    async def handler(send):
        config = await lv.fetch_config(send, url_path)
        if section_sel and not view_sel:
            raise HassError("--section requires --view")
        target = config
        if view_sel:
            _, target = lv.resolve_view(config, view_sel)
        if section_sel:
            _, target = lv.resolve_section(target, section_sel)
        click.echo(lv.dump(target, as_json))

    _run(handler)


@cli.command("cards")
@click.argument("url_path", required=False)
@click.option("--view", "view_sel", help="Limit to one view (title, path, or #index)")
@click.option("--type", "type_filter", help="Filter cards by type substring")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def cards_cmd(
    url_path: str | None,
    view_sel: str | None,
    type_filter: str | None,
    as_json: bool,
) -> None:
    """Summarize cards in a dashboard."""

    async def handler(send):
        config = await lv.fetch_config(send, url_path)
        views = config.get("views", [])
        if view_sel:
            views = [lv.resolve_view(config, view_sel)[1]]

        all_cards = []
        for view in views:
            view_title = view.get("title", view.get("path", "(untitled)"))
            for card in _collect_cards(view):
                card_type = card.get("type", "?")
                if type_filter and type_filter not in card_type:
                    continue
                all_cards.append(
                    {
                        "view": view_title,
                        "type": card_type,
                        "name": card.get("name", card.get("title", "")),
                        "entity": card.get("entity", ""),
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
            click.echo(f"[{c['view']}] {' | '.join(parts)}")

    _run(handler)


@cli.group("card")
def card_group() -> None:
    """Inspect and mutate individual cards on a dashboard."""


def _read_cards(src: str) -> list[dict]:
    """Read and parse a card payload from a file or stdin."""
    if src == "-":
        text = click.get_text_stream("stdin").read()
    else:
        try:
            text = Path(src).read_text()
        except OSError as exc:
            die(f"cannot read {src}: {exc.strerror}")
    try:
        return lv.parse_cards(text)
    except HassError as exc:
        die(str(exc))


async def _verify_entities(send, cards: list[dict] | dict) -> int:
    """Fail unless every entity referenced by ``cards`` exists; returns the count."""
    referenced = lv.collect_entities(cards)
    missing = sorted(referenced - await lv.known_entities(send))
    if missing:
        raise HassError("unknown entities: " + ", ".join(missing))
    return len(referenced)


async def _commit(send, url_path: str | None, original: dict, config: dict) -> None:
    """Back up the pre-write config, then save the modified one."""
    backup = lv.write_backup(url_path, original)
    await lv.save_config(send, url_path, config)
    click.echo(f"backup: {backup}")


def _target_section(config: dict, view_sel: str, section_sel: str) -> tuple[dict, str]:
    """Resolve a section plus a label naming its view and title."""
    view_idx, view = lv.resolve_view(config, view_sel)
    sec_idx, section = lv.resolve_section(view, section_sel)
    label = lv.section_title(section) or f"#{sec_idx}"
    return section, f"view {lv.view_label(view, view_idx)} section '{label}'"


def _card_options(func):
    """Shared --view/--section/--card options for card-addressed commands."""
    func = click.option(
        "--card", "card_sel", required=True, help="Card (#index, name, or entity_id)"
    )(func)
    func = click.option(
        "--section", "section_sel", required=True, help="Section (title or #index)"
    )(func)
    func = click.option(
        "--view", "view_sel", required=True, help="View (title, path, or #index)"
    )(func)
    return click.argument("url_path", required=False)(func)


@card_group.command("list")
@click.argument("url_path", required=False)
@click.option("--view", "view_sel", required=True, help="View (title, path, or #index)")
@click.option(
    "--section", "section_sel", required=True, help="Section (title or #index)"
)
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def card_list_cmd(
    url_path: str | None, view_sel: str, section_sel: str, as_json: bool
) -> None:
    """List a section's cards with the --card selector for each one."""

    async def handler(send):
        config = await lv.fetch_config(send, url_path)
        section, where = _target_section(config, view_sel, section_sel)
        cards = section.get("cards", [])
        selectors = lv.card_selectors(section)
        if as_json:
            click.echo(
                json.dumps(
                    [
                        {"index": i, "selector": s, "card": c}
                        for i, (s, c) in enumerate(zip(selectors, cards, strict=True))
                    ],
                    indent=2,
                )
            )
            return
        click.echo(f"{where}: {len(cards)} card(s)")
        for i, (selector, card) in enumerate(zip(selectors, cards, strict=True)):
            click.echo(f"  {lv.card_label(card, i)}  selector: {selector}")

    _run(handler)


@card_group.command("edit")
@_card_options
@click.option(
    "--file", "-f", "src", required=True, help="Replacement card YAML/JSON ('-' stdin)"
)
@click.option("--dry-run", is_flag=True, help="Show the diff, do not write")
def card_edit_cmd(
    url_path: str | None,
    view_sel: str,
    section_sel: str,
    card_sel: str,
    src: str,
    dry_run: bool,
) -> None:
    """Replace one card in place with new YAML/JSON."""
    cards = _read_cards(src)
    if len(cards) != 1:
        die(f"--file must contain exactly one card, got {len(cards)}")
    new_card = cards[0]

    async def handler(send):
        config = await lv.fetch_config(send, url_path)
        original = copy.deepcopy(config)
        section, where = _target_section(config, view_sel, section_sel)
        idx, old_card = lv.resolve_card(section, card_sel)
        verified = await _verify_entities(send, new_card)

        summary = (
            f"card {lv.card_label(old_card, idx)} in {where}; "
            f"{verified} entity reference(s) verified"
        )
        if dry_run:
            click.echo(f"dry-run: would replace {summary}")
            click.echo(_diff(old_card, new_card))
            return

        section["cards"][idx] = new_card
        await _commit(send, url_path, original, config)
        click.echo(f"replaced {summary}")

    _run(handler)


@card_group.command("remove")
@_card_options
@click.option("--dry-run", is_flag=True, help="Report what would be removed")
def card_remove_cmd(
    url_path: str | None,
    view_sel: str,
    section_sel: str,
    card_sel: str,
    dry_run: bool,
) -> None:
    """Delete one card from a section."""

    async def handler(send):
        config = await lv.fetch_config(send, url_path)
        original = copy.deepcopy(config)
        section, where = _target_section(config, view_sel, section_sel)
        idx, card = lv.resolve_card(section, card_sel)
        summary = f"card {lv.card_label(card, idx)} from {where}"
        if dry_run:
            click.echo(f"dry-run: would remove {summary}")
            return
        del section["cards"][idx]
        await _commit(send, url_path, original, config)
        click.echo(f"removed {summary}")

    _run(handler)


def _diff(old: dict, new: dict) -> str:
    """Unified YAML diff between two card configs."""
    lines = difflib.unified_diff(
        lv.dump(old, as_json=False).splitlines(),
        lv.dump(new, as_json=False).splitlines(),
        lineterm="",
        n=1,
    )
    return "\n".join(list(lines)[2:])


@card_group.command("add")
@click.argument("url_path", required=False)
@click.option("--view", "view_sel", required=True, help="Target view (title/path/#idx)")
@click.option("--section", "section_sel", help="Existing section (title or #index)")
@click.option("--new-section", "new_section", help="Create a section with this title")
@click.option(
    "--file",
    "-f",
    "src",
    required=True,
    help="YAML/JSON file with a card or list of cards ('-' for stdin)",
)
@click.option("--position", type=int, help="Insert index within section (default: end)")
@click.option("--dry-run", is_flag=True, help="Validate and report, do not write")
def card_add_cmd(
    url_path: str | None,
    view_sel: str,
    section_sel: str | None,
    new_section: str | None,
    src: str,
    position: int | None,
    dry_run: bool,
) -> None:
    """Append cards to a view section, validating referenced entities first."""
    if bool(section_sel) == bool(new_section):
        die("specify exactly one of --section or --new-section")
    cards = _read_cards(src)

    async def handler(send):
        config = await lv.fetch_config(send, url_path)
        original = copy.deepcopy(config)
        view_idx, view = lv.resolve_view(config, view_sel)
        verified = await _verify_entities(send, cards)

        if section_sel:
            sec_idx, section = lv.resolve_section(view, section_sel)
        else:
            view.setdefault("sections", []).append(lv.new_section(new_section or ""))
            sec_idx = len(view["sections"]) - 1
            section = view["sections"][sec_idx]

        target = section.setdefault("cards", [])
        at = len(target) if position is None else position
        target[at:at] = cards

        label = lv.section_title(section) or f"#{sec_idx}"
        summary = (
            f"{len(cards)} card(s) into view {lv.view_label(view, view_idx)} "
            f"section '{label}' at index {at}; "
            f"{verified} entity reference(s) verified"
        )
        if dry_run:
            click.echo(f"dry-run: would add {summary}")
            for card in cards:
                click.echo(f"  {card.get('type')} {card.get('entity', '')}".rstrip())
            return

        await _commit(send, url_path, original, config)
        click.echo(f"added {summary}")

    _run(handler)


@cli.command("restore")
@click.argument("backup_file", type=click.Path(exists=True, dir_okay=False))
@click.argument("url_path", required=False)
@click.option("--dry-run", is_flag=True, help="Report what would be restored")
def restore_cmd(backup_file: str, url_path: str | None, dry_run: bool) -> None:
    """Restore a dashboard from a backup written by `card add`."""
    try:
        config = json.loads(Path(backup_file).read_text())
    except json.JSONDecodeError as exc:
        die(f"{backup_file} is not a valid dashboard backup: {exc}")
    views = config.get("views", [])

    async def handler(send):
        summary = f"{len(views)} view(s) from {backup_file} to {url_path or 'overview'}"
        if dry_run:
            click.echo(f"dry-run: would restore {summary}")
            return
        await lv.save_config(send, url_path, config)
        click.echo(f"restored {summary}")

    _run(handler)


def _run(handler) -> None:
    """Run a WebSocket handler, converting domain errors into a clean exit."""
    try:
        run_ws(handler)
    except HassError as exc:
        die(str(exc))
