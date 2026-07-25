"""Tests for Lovelace selector resolution and card parsing helpers."""

from __future__ import annotations

import pytest

from hass import _lovelace as lv
from hass._errors import HassError


def test_collect_entities_walks_nested_structures():
    card = {
        "type": "custom:bubble-card",
        "entity": "switch.a",
        "sub_button": [{"entity": "light.b"}],
        "entities": ["sensor.c", {"entity": "sensor.d"}],
        "visibility": [{"condition": "state", "entity": "input_select.e"}],
    }
    assert lv.collect_entities([card]) == {
        "switch.a",
        "light.b",
        "sensor.c",
        "sensor.d",
        "input_select.e",
    }


def test_collect_entities_skips_templates_and_non_ids():
    card = {"entity": "{{ states.x }}", "entities": ["not_an_entity"]}
    assert lv.collect_entities(card) == set()


def test_parse_cards_accepts_yaml_json_and_lists():
    assert lv.parse_cards("type: button\n") == [{"type": "button"}]
    assert lv.parse_cards('{"type": "button"}') == [{"type": "button"}]
    assert len(lv.parse_cards("- type: a\n- type: b\n")) == 2


@pytest.mark.parametrize(
    "text, expected",
    [("", "empty"), ("entity: x\n", "'type' key"), ("- just a string\n", "mapping")],
)
def test_parse_cards_rejects_bad_input(text, expected):
    with pytest.raises(HassError) as exc:
        lv.parse_cards(text)
    assert expected in str(exc.value)


def _config():
    return {
        "views": [
            {"title": "Home", "sections": [{"type": "grid", "cards": []}]},
            {
                "title": "Pool",
                "path": "",
                "sections": [
                    {
                        "type": "grid",
                        "cards": [{"type": "heading", "heading": "Maint"}],
                    },
                    {"type": "grid", "title": "Extras", "cards": []},
                ],
            },
            {"title": "Front Door", "path": "keymaster_front_door", "sections": []},
        ]
    }


@pytest.mark.parametrize("selector", ["Pool", "pool", "#1"])
def test_resolve_view_by_title_and_index(selector):
    idx, view = lv.resolve_view(_config(), selector)
    assert idx == 1 and view["title"] == "Pool"


def test_resolve_view_by_path():
    idx, _ = lv.resolve_view(_config(), "keymaster_front_door")
    assert idx == 2


def test_resolve_view_unknown_lists_candidates():
    with pytest.raises(HassError) as exc:
        lv.resolve_view(_config(), "Attic")
    assert "#1 Pool" in str(exc.value)


def test_resolve_view_index_out_of_range():
    with pytest.raises(HassError, match="out of range"):
        lv.resolve_view(_config(), "#9")


def test_resolve_section_by_heading_card_and_title():
    view = _config()["views"][1]
    assert lv.resolve_section(view, "Maint")[0] == 0
    assert lv.resolve_section(view, "Extras")[0] == 1
    assert lv.resolve_section(view, "#1")[0] == 1


def test_resolve_section_unknown():
    with pytest.raises(HassError) as exc:
        lv.resolve_section(_config()["views"][1], "Nope")
    assert "#0 Maint" in str(exc.value)


def test_new_section_has_heading_card():
    section = lv.new_section("Speakers")
    assert section["cards"][0]["heading"] == "Speakers"
    assert lv.section_title(section) == "Speakers"


def test_dump_yaml_uses_literal_blocks():
    out = lv.dump({"styles": "a {\n  b: c;\n}\n"}, as_json=False)
    assert out.startswith("styles: |")
    assert "\\n" not in out


def test_write_backup_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(lv, "BACKUP_DIR", tmp_path)
    path = lv.write_backup("lovelace", _config())
    assert path.parent == tmp_path
    assert "lovelace" in path.name
    assert lv.dump(_config(), as_json=True) == path.read_text()


def _section():
    return {
        "type": "grid",
        "cards": [
            {"type": "heading", "heading": "Pool Audio"},
            {
                "type": "custom:bubble-card",
                "card_type": "media-player",
                "entity": "media_player.wiim_patio",
                "name": "Patio Speakers",
            },
            {
                "type": "custom:bubble-card",
                "card_type": "media-player",
                "entity": "media_player.wiim_pool",
                "name": "Pool Speakers",
            },
            {
                "type": "custom:bubble-card",
                "card_type": "pop-up",
                "hash": "#pool-audio",
            },
        ],
    }


@pytest.mark.parametrize(
    "selector, expected",
    [
        ("#2", 2),
        ("Patio Speakers", 1),
        ("patio speakers", 1),
        ("media_player.wiim_pool", 2),
        ("#pool-audio", 3),
        ("Pool Audio", 0),
    ],
)
def test_resolve_card_by_index_name_entity_and_hash(selector, expected):
    idx, _ = lv.resolve_card(_section(), selector)
    assert idx == expected


def test_resolve_card_ambiguous_lists_candidates():
    with pytest.raises(HassError) as exc:
        lv.resolve_card(_section(), "Speakers")
    assert "ambiguous" in str(exc.value)
    assert "#1" in str(exc.value) and "#2" in str(exc.value)


def test_resolve_card_unknown_lists_candidates():
    with pytest.raises(HassError) as exc:
        lv.resolve_card(_section(), "Nope")
    assert "Patio Speakers" in str(exc.value)


def test_resolve_card_index_out_of_range():
    with pytest.raises(HassError, match="out of range"):
        lv.resolve_card(_section(), "#9")


def test_card_label_shows_type_and_identity():
    label = lv.card_label(_section()["cards"][1], 1)
    assert label.startswith("#1 custom:bubble-card")
    assert "Patio Speakers" in label
    assert "media_player.wiim_patio" in label


def test_card_selectors_are_unique_and_resolve_back():
    section = _section()
    selectors = lv.card_selectors(section)
    assert len(selectors) == len(section["cards"])
    for i, selector in enumerate(selectors):
        assert lv.resolve_card(section, selector)[0] == i


def test_card_selectors_fall_back_to_index_when_ambiguous():
    section = {"cards": [{"type": "button"}, {"type": "button"}]}
    assert lv.card_selectors(section) == ["#0", "#1"]
