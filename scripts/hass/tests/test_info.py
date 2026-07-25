"""Tests for the instance info command."""

from __future__ import annotations

import json
from unittest.mock import patch

from click.testing import CliRunner

from hass.cli import cli

RESPONSES = {
    "get_config": {
        "version": "2026.7.4",
        "state": "RUNNING",
        "location_name": "Home",
        "time_zone": "America/Chicago",
        "country": "US",
        "language": "en",
        "config_source": "storage",
        "external_url": "https://ha.example",
        "internal_url": "http://ha.local:8123",
        "safe_mode": False,
        "recovery_mode": False,
        "components": ["light", "sensor"],
    },
    "config_entries/get": [
        {"state": "loaded"},
        {"state": "loaded"},
        {"state": "setup_retry"},
    ],
    "config/device_registry/list": [{}, {}],
    "config/entity_registry/list": [{}, {}, {}],
    "config_entries/flow/progress": [{"flow_id": "a"}],
    "lovelace/dashboards/list": [{"url_path": "lovelace"}],
    "repairs/list_issues": {"issues": [{"ignored": False}, {"ignored": True}]},
}


def _invoke(fake_ws, args):
    ws = fake_ws(RESPONSES)
    with patch("hass.info.run_ws", ws.run):
        return CliRunner().invoke(cli, args)


def test_info_reports_version_and_inventory(fake_ws):
    result = _invoke(fake_ws, ["info"])
    assert result.exit_code == 0
    assert "Home Assistant 2026.7.4 (RUNNING) at Home, America/Chicago" in result.output
    assert "devices=2 entities=3 dashboards=2" in result.output
    assert "Config entries: 3 (loaded=2 setup_retry=1)" in result.output
    assert "Pending discovery flows: 1" in result.output
    assert "Active repairs: 1" in result.output


def test_info_json(fake_ws):
    result = _invoke(fake_ws, ["info", "--json"])
    data = json.loads(result.output)
    assert data["version"] == "2026.7.4"
    assert data["config_entries"] == {"loaded": 2, "setup_retry": 1}
