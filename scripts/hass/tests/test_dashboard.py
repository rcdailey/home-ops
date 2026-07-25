"""Tests for dashboard inspection and card mutation."""

from __future__ import annotations

import json
from unittest.mock import patch

import yaml
from click.testing import CliRunner

from hass.cli import cli


def _config() -> dict:
    return {
        "views": [
            {
                "title": "Home",
                "type": "sections",
                "sections": [{"type": "grid", "cards": []}],
            },
            {
                "title": "Pool",
                "path": "",
                "type": "sections",
                "sections": [
                    {
                        "type": "grid",
                        "cards": [
                            {"type": "heading", "heading": "Maintenance"},
                            {"type": "button", "entity": "switch.pool_cleaner"},
                        ],
                    }
                ],
            },
        ]
    }


def _responses(config: dict, saved: list) -> dict:
    return {
        "lovelace/config": lambda _p: config,
        "lovelace/config/save": lambda p: saved.append(p) or {"success": True},
        "get_states": [
            {"entity_id": "switch.pool_cleaner"},
            {"entity_id": "media_player.wiim_pool"},
        ],
        "config/entity_registry/list": [{"entity_id": "light.pool_led_lights"}],
    }


def _invoke(fake_ws, args, config=None, input=None):
    config = config if config is not None else _config()
    saved: list = []
    ws = fake_ws(_responses(config, saved))
    with patch("hass.dashboard.run_ws", ws.run):
        result = CliRunner().invoke(cli, args, input=input)
    return result, saved, config


def test_views_lists_selectors(fake_ws):
    result, _, _ = _invoke(fake_ws, ["dashboard", "views", "lovelace"])
    assert result.exit_code == 0
    assert "#1 Pool" in result.output
    assert "#0 Maintenance cards=2" in result.output


def test_get_narrows_to_view(fake_ws):
    result, _, _ = _invoke(fake_ws, ["dashboard", "get", "lovelace", "--view", "Pool"])
    assert result.exit_code == 0
    parsed = yaml.safe_load(result.output)
    assert parsed["title"] == "Pool"
    assert "Home" not in result.output


def test_get_narrows_to_section(fake_ws):
    result, _, _ = _invoke(
        fake_ws,
        ["dashboard", "get", "lovelace", "--view", "Pool", "--section", "Maintenance"],
    )
    assert result.exit_code == 0
    parsed = yaml.safe_load(result.output)
    assert parsed["cards"][0]["heading"] == "Maintenance"


def test_get_json_flag(fake_ws):
    result, _, _ = _invoke(
        fake_ws, ["dashboard", "get", "lovelace", "--view", "Pool", "--json"]
    )
    assert json.loads(result.output)["title"] == "Pool"


def test_get_unknown_view_lists_candidates(fake_ws):
    result, _, _ = _invoke(fake_ws, ["dashboard", "get", "lovelace", "--view", "Attic"])
    assert result.exit_code == 1
    assert "no view matching 'Attic'" in result.output
    assert "#1 Pool" in result.output


def test_card_add_appends_to_section(fake_ws):
    card = "type: media-control\nentity: media_player.wiim_pool\n"
    result, saved, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "add",
            "lovelace",
            "--view",
            "Pool",
            "--section",
            "Maintenance",
            "-f",
            "-",
        ],
        input=card,
    )
    assert result.exit_code == 0
    cards = saved[0]["config"]["views"][1]["sections"][0]["cards"]
    assert cards[-1] == {"type": "media-control", "entity": "media_player.wiim_pool"}
    assert "backup:" in result.output


def test_card_add_creates_new_section(fake_ws):
    card = '{"type": "media-control", "entity": "media_player.wiim_pool"}'
    result, saved, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "add",
            "lovelace",
            "--view",
            "Pool",
            "--new-section",
            "Speakers",
            "-f",
            "-",
        ],
        input=card,
    )
    assert result.exit_code == 0
    sections = saved[0]["config"]["views"][1]["sections"]
    assert len(sections) == 2
    assert sections[1]["cards"][0] == {
        "type": "heading",
        "heading": "Speakers",
        "heading_style": "title",
    }
    assert sections[1]["cards"][1]["type"] == "media-control"


def test_card_add_position(fake_ws):
    card = "type: media-control\nentity: media_player.wiim_pool\n"
    _, saved, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "add",
            "lovelace",
            "--view",
            "Pool",
            "--section",
            "Maintenance",
            "-f",
            "-",
            "--position",
            "1",
        ],
        input=card,
    )
    cards = saved[0]["config"]["views"][1]["sections"][0]["cards"]
    assert cards[1]["type"] == "media-control"


def test_card_add_rejects_unknown_entity(fake_ws):
    card = "type: media-control\nentity: media_player.ghost\n"
    result, saved, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "add",
            "lovelace",
            "--view",
            "Pool",
            "--section",
            "Maintenance",
            "-f",
            "-",
        ],
        input=card,
    )
    assert result.exit_code == 1
    assert "unknown entities: media_player.ghost" in result.output
    assert saved == []


def test_card_add_accepts_registry_only_entity(fake_ws):
    card = "type: button\nentity: light.pool_led_lights\n"
    result, saved, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "add",
            "lovelace",
            "--view",
            "Pool",
            "--section",
            "Maintenance",
            "-f",
            "-",
        ],
        input=card,
    )
    assert result.exit_code == 0
    assert saved


def test_card_add_dry_run_does_not_write(fake_ws):
    card = "type: media-control\nentity: media_player.wiim_pool\n"
    result, saved, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "add",
            "lovelace",
            "--view",
            "Pool",
            "--section",
            "Maintenance",
            "-f",
            "-",
            "--dry-run",
        ],
        input=card,
    )
    assert result.exit_code == 0
    assert saved == []
    assert "dry-run: would add 1 card(s)" in result.output


def test_card_add_requires_one_section_option(fake_ws):
    result, saved, _ = _invoke(
        fake_ws,
        ["dashboard", "card", "add", "lovelace", "--view", "Pool", "-f", "-"],
        input="type: button\n",
    )
    assert result.exit_code == 1
    assert "exactly one of --section or --new-section" in result.output
    assert saved == []


def test_card_add_rejects_malformed_card(fake_ws):
    result, saved, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "add",
            "lovelace",
            "--view",
            "Pool",
            "--section",
            "Maintenance",
            "-f",
            "-",
        ],
        input="entity: switch.pool_cleaner\n",
    )
    assert result.exit_code == 1
    assert "'type' key" in result.output
    assert saved == []


def test_card_add_writes_recoverable_backup(fake_ws, tmp_path, monkeypatch):
    monkeypatch.setattr("hass._lovelace.BACKUP_DIR", tmp_path)
    card = "type: media-control\nentity: media_player.wiim_pool\n"
    result, _, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "add",
            "lovelace",
            "--view",
            "Pool",
            "--section",
            "Maintenance",
            "-f",
            "-",
        ],
        input=card,
    )
    backups = list(tmp_path.iterdir())
    assert len(backups) == 1
    restored = json.loads(backups[0].read_text())
    assert len(restored["views"][1]["sections"][0]["cards"]) == 2
    assert str(backups[0]) in result.output


def test_restore_writes_backup_config(fake_ws, tmp_path):
    backup = tmp_path / "lovelace.json"
    backup.write_text(json.dumps(_config()))
    saved: list = []
    ws = fake_ws(_responses(_config(), saved))
    with patch("hass.dashboard.run_ws", ws.run):
        result = CliRunner().invoke(
            cli, ["dashboard", "restore", str(backup), "lovelace"]
        )
    assert result.exit_code == 0
    assert saved[0]["config"]["views"][1]["title"] == "Pool"
    assert "restored 2 view(s)" in result.output


def test_card_list_prints_copyable_selectors(fake_ws):
    result, _, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "list",
            "lovelace",
            "--view",
            "Pool",
            "--section",
            "Maintenance",
        ],
    )
    assert result.exit_code == 0
    assert "#0 heading" in result.output
    assert "switch.pool_cleaner" in result.output
    assert "selector: switch.pool_cleaner" in result.output


def test_card_edit_replaces_target_card(fake_ws):
    card = "type: media-control\nentity: media_player.wiim_pool\n"
    result, saved, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "edit",
            "lovelace",
            "--view",
            "Pool",
            "--section",
            "Maintenance",
            "--card",
            "switch.pool_cleaner",
            "-f",
            "-",
        ],
        input=card,
    )
    assert result.exit_code == 0
    cards = saved[0]["config"]["views"][1]["sections"][0]["cards"]
    assert len(cards) == 2
    assert cards[1] == {"type": "media-control", "entity": "media_player.wiim_pool"}
    assert "backup:" in result.output


def test_card_edit_rejects_unknown_entity(fake_ws):
    result, saved, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "edit",
            "lovelace",
            "--view",
            "Pool",
            "--section",
            "Maintenance",
            "--card",
            "#1",
            "-f",
            "-",
        ],
        input="type: button\nentity: light.ghost\n",
    )
    assert result.exit_code == 1
    assert "unknown entities: light.ghost" in result.output
    assert saved == []


def test_card_edit_requires_single_card(fake_ws):
    result, saved, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "edit",
            "lovelace",
            "--view",
            "Pool",
            "--section",
            "Maintenance",
            "--card",
            "#1",
            "-f",
            "-",
        ],
        input="- type: button\n- type: button\n",
    )
    assert result.exit_code == 1
    assert "exactly one card" in result.output
    assert saved == []


def test_card_edit_dry_run_shows_diff_and_does_not_write(fake_ws):
    result, saved, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "edit",
            "lovelace",
            "--view",
            "Pool",
            "--section",
            "Maintenance",
            "--card",
            "#1",
            "-f",
            "-",
            "--dry-run",
        ],
        input="type: media-control\nentity: media_player.wiim_pool\n",
    )
    assert result.exit_code == 0
    assert saved == []
    assert "-type: button" in result.output
    assert "+type: media-control" in result.output


def test_card_remove_deletes_target_card(fake_ws, tmp_path, monkeypatch):
    monkeypatch.setattr("hass._lovelace.BACKUP_DIR", tmp_path)
    result, saved, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "remove",
            "lovelace",
            "--view",
            "Pool",
            "--section",
            "Maintenance",
            "--card",
            "switch.pool_cleaner",
        ],
    )
    assert result.exit_code == 0
    cards = saved[0]["config"]["views"][1]["sections"][0]["cards"]
    assert [c["type"] for c in cards] == ["heading"]
    assert "backup:" in result.output


def test_card_remove_dry_run_does_not_write(fake_ws):
    result, saved, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "remove",
            "lovelace",
            "--view",
            "Pool",
            "--section",
            "Maintenance",
            "--card",
            "#1",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert saved == []
    assert "dry-run: would remove" in result.output


def test_card_remove_unknown_selector_lists_candidates(fake_ws):
    result, saved, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "remove",
            "lovelace",
            "--view",
            "Pool",
            "--section",
            "Maintenance",
            "--card",
            "Nope",
        ],
    )
    assert result.exit_code == 1
    assert "no card matching 'Nope'" in result.output
    assert saved == []


def test_card_edit_missing_file_reports_cleanly(fake_ws):
    result, saved, _ = _invoke(
        fake_ws,
        [
            "dashboard",
            "card",
            "edit",
            "lovelace",
            "--view",
            "Pool",
            "--section",
            "Maintenance",
            "--card",
            "#1",
            "-f",
            "/nonexistent/card.yaml",
        ],
    )
    assert result.exit_code == 1
    assert "cannot read /nonexistent/card.yaml" in result.output
    assert saved == []
