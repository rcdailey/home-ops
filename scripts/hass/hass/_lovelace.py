"""Lovelace config fetch/save, selector resolution, and card validation."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from hass._client import Send, ws_error
from hass._errors import HassError

BACKUP_DIR = Path.home() / ".cache" / "hass" / "lovelace"


async def fetch_config(send: Send, url_path: str | None) -> dict:
    """Return the full config for a dashboard (None url_path = Overview)."""
    payload: dict = {"type": "lovelace/config"}
    if url_path:
        payload["url_path"] = url_path
    msg = await send(payload)
    if not msg.get("success"):
        raise HassError(ws_error(msg))
    return msg["result"]


async def save_config(send: Send, url_path: str | None, config: dict) -> None:
    """Overwrite a dashboard config."""
    payload: dict = {"type": "lovelace/config/save", "config": config}
    if url_path:
        payload["url_path"] = url_path
    msg = await send(payload)
    if not msg.get("success"):
        raise HassError(ws_error(msg))


async def known_entities(send: Send) -> set[str]:
    """Return every entity_id HA knows: live states plus registry entries."""
    states = await send({"type": "get_states"})
    if not states.get("success"):
        raise HassError(ws_error(states))
    ids = {s["entity_id"] for s in states["result"]}
    registry = await send({"type": "config/entity_registry/list"})
    if registry.get("success"):
        ids |= {e["entity_id"] for e in registry["result"]}
    return ids


def view_label(view: dict, index: int) -> str:
    """Human-readable identity of a view."""
    title = view.get("title") or "(untitled)"
    path = view.get("path")
    return f"#{index} {title}" + (f" [{path}]" if path else "")


def resolve_view(config: dict, selector: str) -> tuple[int, dict]:
    """Resolve a view by title, path, or ``#index``. Raises on miss/ambiguity."""
    views = config.get("views", [])
    if not views:
        raise HassError("dashboard has no views")

    if selector.startswith("#"):
        idx = int(selector[1:])
        if idx >= len(views):
            raise HassError(f"view index {idx} out of range (0..{len(views) - 1})")
        return idx, views[idx]

    want = selector.strip().casefold()
    matches = [
        (i, v)
        for i, v in enumerate(views)
        if (v.get("title") or "").casefold() == want
        or (v.get("path") or "").casefold() == want
    ]
    if not matches:
        matches = [
            (i, v)
            for i, v in enumerate(views)
            if want in (v.get("title") or "").casefold()
        ]
    if not matches:
        known = ", ".join(view_label(v, i) for i, v in enumerate(views))
        raise HassError(f"no view matching '{selector}'; views: {known}")
    if len(matches) > 1:
        found = ", ".join(view_label(v, i) for i, v in matches)
        raise HassError(f"ambiguous view '{selector}': {found}")
    return matches[0]


def section_title(section: dict) -> str:
    """Section title, falling back to its leading heading card."""
    if section.get("title"):
        return section["title"]
    for card in section.get("cards", []):
        if card.get("type") == "heading":
            return card.get("heading", "")
    return ""


def resolve_section(view: dict, selector: str) -> tuple[int, dict]:
    """Resolve a section by title or ``#index`` within a view."""
    sections = view.get("sections", [])
    if not sections:
        raise HassError("view has no sections")

    if selector.startswith("#"):
        idx = int(selector[1:])
        if idx >= len(sections):
            raise HassError(
                f"section index {idx} out of range (0..{len(sections) - 1})"
            )
        return idx, sections[idx]

    want = selector.strip().casefold()
    matches = [
        (i, s) for i, s in enumerate(sections) if section_title(s).casefold() == want
    ]
    if not matches:
        matches = [
            (i, s)
            for i, s in enumerate(sections)
            if want in section_title(s).casefold()
        ]
    if not matches:
        known = ", ".join(f"#{i} {section_title(s)}" for i, s in enumerate(sections))
        raise HassError(f"no section matching '{selector}'; sections: {known}")
    if len(matches) > 1:
        found = ", ".join(f"#{i} {section_title(s)}" for i, s in matches)
        raise HassError(f"ambiguous section '{selector}': {found}")
    return matches[0]


def card_names(card: dict) -> list[str]:
    """Human-facing identifiers of a card, in descending order of stability."""
    keys = ("name", "heading", "title", "hash", "entity")
    return [str(card[k]) for k in keys if isinstance(card.get(k), str) and card[k]]


def card_label(card: dict, index: int) -> str:
    """One-line identity of a card within its section."""
    parts = [f"#{index}", card.get("type", "?")]
    if card.get("card_type"):
        parts.append(str(card["card_type"]))
    parts += card_names(card)
    return " ".join(parts)


def resolve_card(section: dict, selector: str) -> tuple[int, dict]:
    """Resolve a card within a section by ``#index``, name, hash, or entity_id."""
    cards = section.get("cards", [])
    if not cards:
        raise HassError("section has no cards")

    if selector.startswith("#") and selector[1:].isdigit():
        idx = int(selector[1:])
        if idx >= len(cards):
            raise HassError(f"card index {idx} out of range (0..{len(cards) - 1})")
        return idx, cards[idx]

    want = selector.strip().casefold()
    matches = [
        (i, c)
        for i, c in enumerate(cards)
        if any(n.casefold() == want for n in card_names(c))
    ]
    if not matches:
        matches = [
            (i, c)
            for i, c in enumerate(cards)
            if any(want in n.casefold() for n in card_names(c))
        ]
    if not matches:
        known = "; ".join(card_label(c, i) for i, c in enumerate(cards))
        raise HassError(f"no card matching '{selector}'; cards: {known}")
    if len(matches) > 1:
        found = "; ".join(card_label(c, i) for i, c in matches)
        raise HassError(f"ambiguous card '{selector}': {found}")
    return matches[0]


def card_selectors(section: dict) -> list[str]:
    """Return a copy-pasteable, unambiguous selector for every card in a section."""
    selectors = []
    for i, card in enumerate(section.get("cards", [])):
        chosen = f"#{i}"
        for name in card_names(card):
            try:
                if resolve_card(section, name)[0] == i:
                    chosen = name
                    break
            except HassError:
                continue
        selectors.append(chosen)
    return selectors


def new_section(title: str) -> dict:
    """Build an empty grid section with a heading card."""
    return {
        "type": "grid",
        "cards": [{"type": "heading", "heading": title, "heading_style": "title"}],
    }


_TEMPLATE = re.compile(r"\{\{|\{%")


def collect_entities(obj: Any) -> set[str]:
    """Collect every entity_id referenced by ``entity``/``entities`` keys."""
    found: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "entity" and isinstance(value, str):
                found.add(value)
            elif key == "entities" and isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        found.add(item)
                    else:
                        found |= collect_entities(item)
            else:
                found |= collect_entities(value)
    elif isinstance(obj, list):
        for item in obj:
            found |= collect_entities(item)
    return {e for e in found if "." in e and not _TEMPLATE.search(e)}


def parse_cards(text: str) -> list[dict]:
    """Parse YAML or JSON input into a list of card dicts."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise HassError(f"input is not valid YAML/JSON: {exc}") from None
    if data is None:
        raise HassError("input is empty")
    cards = data if isinstance(data, list) else [data]
    for card in cards:
        if not isinstance(card, dict):
            raise HassError("each card must be a mapping")
        if "type" not in card:
            raise HassError("each card must have a 'type' key")
    return cards


def write_backup(url_path: str | None, config: dict) -> Path:
    """Stash the pre-write dashboard config; returns the backup path."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    path = BACKUP_DIR / f"{url_path or 'overview'}-{stamp}.json"
    path.write_text(json.dumps(config, indent=2))
    return path


class _Dumper(yaml.SafeDumper):
    """YAML dumper that renders multi-line strings as literal blocks."""


def _str_representer(dumper: yaml.SafeDumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_representer)


def dump(obj: Any, as_json: bool) -> str:
    """Serialize config output as JSON or YAML."""
    if as_json:
        return json.dumps(obj, indent=2)
    text = yaml.dump(
        obj, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100
    )
    return text.rstrip()
