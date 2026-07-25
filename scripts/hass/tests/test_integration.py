"""Tests for config entry triage and discovery flow handling."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from hass.cli import cli

ENTRIES = [
    {
        "entry_id": "e1",
        "domain": "wiim",
        "title": "WiiM Pool",
        "state": "loaded",
        "source": "zeroconf",
        "disabled_by": None,
        "reason": None,
    },
    {
        "entry_id": "e2",
        "domain": "ecobee",
        "title": "Ecobee Cloud",
        "state": "not_loaded",
        "source": "user",
        "disabled_by": "user",
        "reason": None,
    },
    {
        "entry_id": "e3",
        "domain": "homekit_controller",
        "title": "Master Ecobee",
        "state": "setup_retry",
        "source": "zeroconf",
        "disabled_by": None,
        "reason": "Network unreachable",
    },
    {
        "entry_id": "e4",
        "domain": "roku",
        "title": "Living Room",
        "state": "not_loaded",
        "source": "ignore",
        "disabled_by": None,
        "reason": None,
    },
]

FLOWS = [
    {
        "flow_id": "abc123",
        "handler": "dlna_dmr",
        "step_id": "confirm",
        "context": {"source": "ssdp", "title_placeholders": {"name": "WiiM Pool"}},
    },
    {
        "flow_id": "def456",
        "handler": "brother",
        "step_id": "confirm",
        "context": {
            "source": "zeroconf",
            "title_placeholders": {"name": "HL-L8430CDW"},
        },
    },
]


def _responses(flows=FLOWS, ignore_result=None):
    return {
        "config_entries/get": ENTRIES,
        "config/device_registry/list": [
            {"config_entries": ["e1"]},
            {"config_entries": ["e2"]},
        ],
        "config/entity_registry/list": [
            {"entity_id": "media_player.wiim_pool", "config_entry_id": "e1"},
            {"entity_id": "sensor.a", "config_entry_id": "e1"},
            {"entity_id": "climate.b", "config_entry_id": "e2"},
        ],
        "config_entries/flow/progress": flows,
        "config_entries/ignore_flow": ignore_result or {"success": True, "result": {}},
    }


def _invoke(fake_ws, args, responses=None):
    ws = fake_ws(responses or _responses())
    with patch("hass.integration.run_ws", ws.run):
        result = CliRunner().invoke(cli, args)
    return result, ws


def test_list_reports_problems_with_counts(fake_ws):
    result, _ = _invoke(fake_ws, ["integration", "list"])
    assert result.exit_code == 0
    assert (
        "4 config entries: loaded=1 not_loaded=2 setup_retry=1 ignored=1"
        in result.output
    )
    assert "1 entry(s) in an error state:" in result.output
    assert "reason=Network unreachable" in result.output
    assert (
        "ecobee: Ecobee Cloud | not_loaded | disabled_by=user | devices=1 entities=1"
        in result.output
    )
    assert "wiim" not in result.output


def test_list_all_includes_loaded_with_counts(fake_ws):
    result, _ = _invoke(fake_ws, ["integration", "list", "--all"])
    assert "wiim: WiiM Pool | devices=1 entities=2" in result.output


def test_list_domain_filter_includes_ignored(fake_ws):
    result, _ = _invoke(fake_ws, ["integration", "list", "roku"])
    assert result.exit_code == 0
    assert "roku: Living Room | ignored" in result.output


def test_discovered_flags_duplicate_of_existing_entry(fake_ws):
    result, _ = _invoke(fake_ws, ["integration", "discovered"])
    assert result.exit_code == 0
    assert "dlna_dmr/wiim-pool | WiiM Pool | via ssdp" in result.output
    assert "duplicate of wiim 'WiiM Pool' (loaded)" in result.output
    lines = result.output.splitlines()
    brother = next(i for i, ln in enumerate(lines) if "brother" in ln)
    assert "duplicate" not in lines[brother + 1]


def test_discovered_empty(fake_ws):
    result, _ = _invoke(fake_ws, ["integration", "discovered"], _responses(flows=[]))
    assert "(no pending discovery flows)" in result.output


def test_ignore_by_slug_selector(fake_ws):
    result, ws = _invoke(fake_ws, ["integration", "ignore", "dlna_dmr/wiim-pool"])
    assert result.exit_code == 0
    sent = ws.payloads("config_entries/ignore_flow")[0]
    assert sent["flow_id"] == "abc123"
    assert sent["title"] == "WiiM Pool"
    assert "ignored dlna_dmr discovery 'WiiM Pool'" in result.output


def test_ignore_by_title_substring(fake_ws):
    result, ws = _invoke(fake_ws, ["integration", "ignore", "hl-l8430"])
    assert result.exit_code == 0
    assert ws.payloads("config_entries/ignore_flow")[0]["flow_id"] == "def456"


def test_ignore_by_flow_id(fake_ws):
    result, ws = _invoke(fake_ws, ["integration", "ignore", "abc123"])
    assert result.exit_code == 0
    assert ws.payloads("config_entries/ignore_flow")[0]["flow_id"] == "abc123"


def test_ignore_unknown_selector_lists_pending(fake_ws):
    result, ws = _invoke(fake_ws, ["integration", "ignore", "nope"])
    assert result.exit_code == 1
    assert "dlna_dmr/wiim-pool" in result.output
    assert ws.payloads("config_entries/ignore_flow") == []


def test_ignore_ambiguous_selector(fake_ws):
    flows = [
        dict(FLOWS[0]),
        {**FLOWS[0], "flow_id": "xyz"},
    ]
    result, ws = _invoke(
        fake_ws, ["integration", "ignore", "wiim"], _responses(flows=flows)
    )
    assert result.exit_code == 1
    assert "ambiguous" in result.output
    assert ws.payloads("config_entries/ignore_flow") == []


def test_ignore_reports_api_failure(fake_ws):
    responses = _responses(
        ignore_result={"success": False, "error": {"message": "flow gone"}}
    )
    result, _ = _invoke(fake_ws, ["integration", "ignore", "abc123"], responses)
    assert result.exit_code == 1
    assert "flow gone" in result.output
