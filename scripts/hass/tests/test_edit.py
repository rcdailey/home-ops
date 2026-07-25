"""Tests for the pull/edit/push round trip."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from hass._errors import HassError
from hass.cli import cli


class FakeRest:
    """In-memory stand-in for HA's config REST endpoints."""

    def __init__(self, store: dict[str, dict] | None = None, normalize=None):
        self.store = store if store is not None else {}
        self.normalize = normalize or (lambda body: body)
        self.writes = 0

    def __call__(self, method: str, path: str, payload=None):
        if method == "GET":
            if path not in self.store:
                raise HassError("HTTP 404: Resource not found")
            return json.loads(json.dumps(self.store[path]))
        if method == "POST":
            self.writes += 1
            self.store[path] = self.normalize(json.loads(json.dumps(payload)))
            return {"result": "ok"}
        if method == "DELETE":
            del self.store[path]
            return {"result": "ok"}
        raise AssertionError(method)


AUTOMATION = {
    "id": "42",
    "alias": "Pool Pump",
    "description": "",
    "triggers": [{"trigger": "state", "entity_id": "input_select.pool"}],
    "actions": [{"action": "switch.turn_on"}],
    "mode": "single",
}

PATH = "config/automation/config/42"


def _invoke(args, rest, input=None):
    with patch("hass._target.rest_call", rest):
        return CliRunner().invoke(cli, args, input=input)


@pytest.fixture
def rest():
    return FakeRest({PATH: AUTOMATION})


@pytest.fixture
def pulled(tmp_path, rest):
    path = tmp_path / "a.yaml"
    result = _invoke(["edit", "pull", "automation", "42", "-o", str(path)], rest)
    assert result.exit_code == 0, result.output
    return path


def _edit(path: Path, old: str, new: str) -> None:
    path.write_text(path.read_text().replace(old, new))


def test_pull_writes_self_describing_file(pulled):
    text = pulled.read_text()
    assert "# hass-edit-kind: automation" in text
    assert "# hass-edit-ref: 42" in text
    assert "# hass-edit-digest: sha256:" in text
    assert yaml.safe_load(text) == AUTOMATION


def test_push_unchanged_is_a_noop(pulled, rest):
    result = _invoke(["edit", "push", str(pulled)], rest)
    assert result.exit_code == 0, result.output
    assert "no changes" in result.output
    assert rest.writes == 0


def test_push_applies_edit_and_shows_diff(pulled, rest):
    _edit(pulled, "alias: Pool Pump", "alias: Pool Pump 2")
    result = _invoke(["edit", "push", str(pulled)], rest)
    assert result.exit_code == 0, result.output
    assert "-alias: Pool Pump" in result.output
    assert "+alias: Pool Pump 2" in result.output
    assert rest.store[PATH]["alias"] == "Pool Pump 2"


def test_push_preserves_key_order(pulled, rest):
    _edit(pulled, "mode: single", "mode: queued")
    _invoke(["edit", "push", str(pulled)], rest)
    assert list(rest.store[PATH]) == list(AUTOMATION)


def test_dry_run_shows_diff_without_writing(pulled, rest):
    _edit(pulled, "mode: single", "mode: queued")
    result = _invoke(["edit", "push", str(pulled), "--dry-run"], rest)
    assert result.exit_code == 0
    assert "dry-run: would update automation 42" in result.output
    assert "+mode: queued" in result.output
    assert rest.store[PATH]["mode"] == "single"


def test_push_refuses_when_upstream_drifted(pulled, rest):
    rest.store[PATH] = {**AUTOMATION, "description": "changed elsewhere"}
    _edit(pulled, "mode: single", "mode: queued")
    result = _invoke(["edit", "push", str(pulled)], rest)
    assert result.exit_code == 1
    assert "changed upstream since it was pulled" in result.output
    assert "-description: changed elsewhere" in result.output
    assert rest.store[PATH]["mode"] == "single"


def test_force_overrides_drift(pulled, rest):
    rest.store[PATH] = {**AUTOMATION, "description": "changed elsewhere"}
    _edit(pulled, "mode: single", "mode: queued")
    result = _invoke(["edit", "push", str(pulled), "--force"], rest)
    assert result.exit_code == 0, result.output
    assert rest.store[PATH]["mode"] == "queued"
    assert rest.store[PATH]["description"] == ""


def test_push_reports_upstream_normalization(pulled, rest):
    rest.normalize = lambda body: {**body, "max": 10}
    _edit(pulled, "mode: single", "mode: queued")
    result = _invoke(["edit", "push", str(pulled)], rest)
    assert result.exit_code == 0, result.output
    assert "note: HA rewrote the stored config" in result.output
    assert "+max: 10" in result.output


def test_push_json_output(pulled, rest):
    _edit(pulled, "mode: single", "mode: queued")
    result = _invoke(["edit", "push", str(pulled), "--json"], rest)
    payload = json.loads(result.output)
    assert payload["status"] == "pushed"
    assert payload["target"] == "automation 42"
    assert "+mode: queued" in payload["diff"]


def test_push_without_header_is_recoverable(tmp_path, rest):
    path = tmp_path / "bare.yaml"
    path.write_text("alias: Pool Pump\n")
    result = _invoke(["edit", "push", str(path)], rest)
    assert result.exit_code == 1
    assert "no hass-edit header" in result.output
    assert "re-pull" in result.output


def test_push_with_partial_header_names_the_gap(tmp_path, rest):
    path = tmp_path / "partial.yaml"
    path.write_text("# hass-edit-kind: automation\nalias: x\n")
    result = _invoke(["edit", "push", str(path)], rest)
    assert result.exit_code == 1
    assert "missing digest" in result.output


def test_push_survives_body_rewrite_as_long_as_header_stays(pulled, rest):
    header = [ln for ln in pulled.read_text().splitlines() if ln.startswith("#")]
    body = dict(AUTOMATION)
    body["mode"] = "queued"
    pulled.write_text("\n".join(header) + "\n" + json.dumps(body))
    result = _invoke(["edit", "push", str(pulled)], rest)
    assert result.exit_code == 0, result.output
    assert rest.store[PATH]["mode"] == "queued"


def test_push_missing_upstream_points_at_create(pulled, rest):
    del rest.store[PATH]
    result = _invoke(["edit", "push", str(pulled)], rest)
    assert result.exit_code == 1
    assert "hass edit create" in result.output


def test_create_and_delete(tmp_path, rest):
    src = tmp_path / "new.yaml"
    src.write_text("alias: New One\ntriggers: []\nactions: []\n")

    result = _invoke(["edit", "create", "automation", "99", "-f", str(src)], rest)
    assert result.exit_code == 0, result.output
    assert rest.store["config/automation/config/99"]["alias"] == "New One"

    result = _invoke(["edit", "create", "automation", "99", "-f", str(src)], rest)
    assert result.exit_code == 1
    assert "already exists" in result.output

    result = _invoke(["edit", "delete", "automation", "99"], rest)
    assert result.exit_code == 0, result.output
    assert "deleted automation 99 ('New One')" in result.output
    assert "config/automation/config/99" not in rest.store


def test_create_dry_run_does_not_write(tmp_path, rest):
    src = tmp_path / "new.yaml"
    src.write_text("alias: New One\n")
    result = _invoke(
        ["edit", "create", "automation", "99", "-f", str(src), "--dry-run"], rest
    )
    assert result.exit_code == 0
    assert "config/automation/config/99" not in rest.store


def test_delete_unknown_automation(rest):
    result = _invoke(["edit", "delete", "automation", "nope"], rest)
    assert result.exit_code == 1
    assert "no such automation nope" in result.output


VIEW_CONFIG = {
    "views": [
        {"title": "Home", "cards": []},
        {"title": "Pool", "cards": [{"type": "button", "entity": "switch.pool"}]},
    ]
}


def _view_invoke(fake_ws, args, config, saved):
    ws = fake_ws(
        {
            "lovelace/config": lambda _p: config,
            "lovelace/config/save": lambda p: saved.append(p) or {"success": True},
        }
    )
    with patch("hass._target.run_ws", ws.run):
        return CliRunner().invoke(cli, args)


def test_view_round_trip(fake_ws, tmp_path):
    config = json.loads(json.dumps(VIEW_CONFIG))
    saved: list = []
    path = tmp_path / "pool.yaml"

    result = _view_invoke(
        fake_ws,
        ["edit", "pull", "view", "lovelace", "--view", "Pool", "-o", str(path)],
        config,
        saved,
    )
    assert result.exit_code == 0, result.output
    assert "# hass-edit-view: Pool" in path.read_text()

    result = _view_invoke(fake_ws, ["edit", "push", str(path)], config, saved)
    assert result.exit_code == 0, result.output
    assert "no changes" in result.output
    assert saved == []

    _edit(path, "title: Pool", "title: Pool Deck")
    result = _view_invoke(fake_ws, ["edit", "push", str(path)], config, saved)
    assert result.exit_code == 0, result.output
    assert saved[0]["config"]["views"][1]["title"] == "Pool Deck"
    assert saved[0]["config"]["views"][0]["title"] == "Home"


def test_view_pull_unknown_view(fake_ws, tmp_path):
    result = _view_invoke(
        fake_ws,
        [
            "edit",
            "pull",
            "view",
            "lovelace",
            "--view",
            "Attic",
            "-o",
            str(tmp_path / "x"),
        ],
        json.loads(json.dumps(VIEW_CONFIG)),
        [],
    )
    assert result.exit_code == 1
    assert "no view matching 'Attic'" in result.output
    assert "#1 Pool" in result.output
