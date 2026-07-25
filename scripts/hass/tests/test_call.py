"""Tests for the service call command and WebSocket error surfacing."""

from __future__ import annotations

import json
from unittest.mock import patch

from click.testing import CliRunner

from hass._client import ws_error
from hass.cli import cli

_NOT_SUPPORTED = {
    "success": False,
    "error": {
        "code": "service_validation_error",
        "message": (
            "Validation error: Entity media_player.wiim_patio does not support "
            "action media_player.join"
        ),
        "translation_key": "service_not_supported",
    },
}


def test_ws_error_uses_translation_key_as_label():
    assert ws_error(_NOT_SUPPORTED) == (
        "ServiceNotSupported: Entity media_player.wiim_patio does not support "
        "action media_player.join"
    )


def test_ws_error_falls_back_to_code():
    msg = {"success": False, "error": {"code": "not_found", "message": "nope"}}
    assert ws_error(msg) == "not_found: nope"


def test_ws_error_without_error_object_dumps_message():
    assert "weird" in ws_error({"success": False, "result": "weird"})


def _invoke(fake_ws, args, responses=None, input=None):
    ws = fake_ws(responses or {"call_service": {"context": {"id": "abc"}}})
    with patch("hass.call.run_ws", ws.run):
        result = CliRunner().invoke(cli, args, input=input)
    return result, ws


def test_call_sends_entity_target_and_data(fake_ws):
    result, ws = _invoke(
        fake_ws,
        [
            "call",
            "media_player.volume_set",
            "media_player.wiim_patio",
            "--data",
            '{"volume_level": 0.22}',
        ],
    )
    assert result.exit_code == 0
    payload = ws.payloads("call_service")[0]
    assert payload["domain"] == "media_player"
    assert payload["service"] == "volume_set"
    assert payload["target"] == {"entity_id": ["media_player.wiim_patio"]}
    assert payload["service_data"] == {"volume_level": 0.22}
    assert "media_player.volume_set" in result.output


def test_call_accepts_yaml_data_and_stdin(fake_ws):
    result, ws = _invoke(
        fake_ws,
        ["call", "light.turn_on", "light.office", "--data", "-"],
        input="brightness: 40\n",
    )
    assert result.exit_code == 0
    assert ws.payloads("call_service")[0]["service_data"] == {"brightness": 40}


def test_call_without_entity_omits_target(fake_ws):
    _, ws = _invoke(fake_ws, ["call", "homeassistant.check_config"])
    assert "target" not in ws.payloads("call_service")[0]


def test_call_surfaces_home_assistant_error(fake_ws):
    result, _ = _invoke(
        fake_ws,
        [
            "call",
            "media_player.join",
            "media_player.wiim_patio",
            "--data",
            '{"group_members": ["media_player.wiim_pool"]}',
        ],
        responses={"call_service": _NOT_SUPPORTED},
    )
    assert result.exit_code == 1
    assert (
        "ServiceNotSupported: Entity media_player.wiim_patio does not support "
        "action media_player.join" in result.output
    )


def test_call_rejects_malformed_service_name(fake_ws):
    result, _ = _invoke(fake_ws, ["call", "volume_set"])
    assert result.exit_code == 1
    assert "domain.service" in result.output


def test_call_response_flag_prints_result(fake_ws):
    result, ws = _invoke(
        fake_ws,
        ["call", "weather.get_forecasts", "weather.home", "--response", "--json"],
        responses={"call_service": {"response": {"weather.home": {"forecast": []}}}},
    )
    assert result.exit_code == 0
    assert ws.payloads("call_service")[0]["return_response"] is True
    assert json.loads(result.output)["response"]["weather.home"] == {"forecast": []}


def test_rest_error_unwraps_json_message():
    from hass._client import rest_error

    assert rest_error(400, '{"message": "not a valid entity"}') == (
        "HTTP 400: not a valid entity"
    )


def test_rest_error_points_service_failures_at_call():
    from hass._client import rest_error

    text = rest_error(500, "500 Internal Server Error\n\nServer got itself in trouble")
    assert text.startswith("HTTP 500: 500 Internal Server Error")
    assert "use `hass call`" in text


def test_trigger_surfaces_home_assistant_error(fake_ws):
    ws = fake_ws({"call_service": _NOT_SUPPORTED})
    with patch("hass.trigger.run_ws", ws.run):
        result = CliRunner().invoke(cli, ["trigger", "script.missing"])
    assert result.exit_code == 1
    assert "ServiceNotSupported:" in result.output


def test_trigger_script_passes_variables(fake_ws):
    ws = fake_ws({"call_service": {"context": {"id": "x"}}})
    with patch("hass.trigger.run_ws", ws.run):
        result = CliRunner().invoke(
            cli, ["trigger", "script.set_mode", "--vars", '{"hdr_mode": "user_4"}']
        )
    assert result.exit_code == 0
    payload = ws.payloads("call_service")[0]
    assert payload["domain"] == "script" and payload["service"] == "set_mode"
    assert payload["service_data"] == {"hdr_mode": "user_4"}
