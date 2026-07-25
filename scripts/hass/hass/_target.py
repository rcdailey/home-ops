"""Editable-object targets: identifier resolution, transport, and file headers.

An "editable object" is anything that can be pulled to a YAML file, edited as
text, and pushed back: a storage-mode automation, a script, or one Lovelace
dashboard view. Each pulled file carries a comment header naming its target and
the digest of the upstream object at pull time, so a push needs only the path.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from hass import _lovelace as lv
from hass._client import get_client, rest_call, rest_get, run_ws
from hass._errors import HassError

EDIT_DIR = Path.home() / ".cache" / "hass" / "edit"

KINDS = ("automation", "script", "view")


def digest(config: Any) -> str:
    """Content digest of a config, insensitive to key ordering."""
    body = json.dumps(config, sort_keys=True, default=str).encode()
    return "sha256:" + hashlib.sha256(body).hexdigest()


def resolve_automation_id(identifier: str) -> str:
    """Resolve an automation entity_id to its storage UUID (UUIDs pass through)."""
    if not identifier.startswith("automation."):
        return identifier
    from homeassistant_api.errors import EndpointNotFoundError

    with get_client() as client:
        try:
            state = client.get_state(entity_id=identifier)
        except EndpointNotFoundError:
            raise HassError(f"entity not found: {identifier}") from None
    config_id = state.attributes.get("id", "")
    if not config_id:
        raise HassError(
            f"{identifier} has no config id; only storage-mode automations are editable"
        )
    return str(config_id)


def _registry_unique_id(entity_id: str) -> str | None:
    """A script's registry ``unique_id`` is its YAML slug under ``script:``."""
    result: dict = {}

    async def handler(send):
        result.update(
            await send({"type": "config/entity_registry/get", "entity_id": entity_id})
        )

    run_ws(handler)
    if result.get("success"):
        return result.get("result", {}).get("unique_id")
    return None


def resolve_script_slug(identifier: str) -> str:
    """Resolve a script entity_id or slug to the slug its config is stored under.

    A customized entity_id diverges from the slug, so the registry is consulted
    as a fallback; candidates are probed against the config endpoint.
    """
    candidates = [identifier.removeprefix("script.")]
    if identifier.startswith("script."):
        resolved = _registry_unique_id(identifier)
        if resolved and resolved not in candidates:
            candidates.append(resolved)
    for slug in candidates:
        if rest_get(f"config/script/config/{slug}") is not None:
            return slug
    raise HassError(
        f"script config not found for {identifier} (tried: {', '.join(candidates)})"
    )


@dataclass(frozen=True)
class Target:
    """An addressable editable object."""

    kind: str
    ref: str = ""
    view: str = ""

    @property
    def label(self) -> str:
        if self.kind == "view":
            return f"view '{self.view}' on dashboard {self.ref or 'overview'}"
        return f"{self.kind} {self.ref}"

    @property
    def slug(self) -> str:
        """Filesystem-safe basename for the pulled file."""
        parts = [self.kind, self.ref or "overview"]
        if self.view:
            parts.append(self.view)
        return re.sub(r"[^A-Za-z0-9_.-]+", "-", "-".join(parts)).strip("-").lower()

    @property
    def _path(self) -> str:
        return f"config/{self.kind}/config/{self.ref}"

    def fetch(self) -> dict | None:
        """Current upstream config, or None if the object does not exist."""
        if self.kind == "view":
            config, idx = self._fetch_view()
            return config["views"][idx]
        return rest_get(self._path)

    def _fetch_view(self) -> tuple[dict, int]:
        """Return the whole dashboard config plus the index of the addressed view.

        An unresolvable selector raises with the candidate list rather than
        reporting absence: views are addressed by title, not by a stable id.
        """
        result: dict = {}

        async def handler(send):
            result["config"] = await lv.fetch_config(send, self.ref or None)

        run_ws(handler)
        config = result["config"]
        return config, lv.resolve_view(config, self.view)[0]

    def push(self, body: dict) -> None:
        """Replace the upstream object with ``body``."""
        if self.kind == "view":
            config, idx = self._fetch_view()
            config["views"][idx] = body

            async def handler(send):
                await lv.save_config(send, self.ref or None, config)

            run_ws(handler)
            return
        rest_call("POST", self._path, body)

    def delete(self) -> None:
        """Remove the upstream object."""
        if self.kind == "view":
            raise HassError("deleting dashboard views is not supported")
        rest_call("DELETE", self._path)


HEADER_KEY = re.compile(r"^\s*#\s*hass-edit-(kind|ref|view|digest)\s*:\s*(.*?)\s*$")

_HEADER_HELP = (
    "the file must keep the '# hass-edit-*' header written by `hass edit pull`; "
    "re-pull to restore it"
)


def render(target: Target, config: Any, path: Path) -> str:
    """Serialize a pulled object as a self-describing YAML file."""
    lines = [
        f"# hass-edit-kind: {target.kind}",
        f"# hass-edit-ref: {target.ref}",
    ]
    if target.view:
        lines.append(f"# hass-edit-view: {target.view}")
    lines += [
        f"# hass-edit-digest: {digest(config)}",
        f"# Edit below, then: hass.sh edit push {path}",
        "",
        lv.dump(config, as_json=False),
        "",
    ]
    return "\n".join(lines)


def parse(text: str, source: str) -> tuple[Target, str, dict]:
    """Parse a pulled file into its target, pull-time digest, and edited body."""
    fields = {}
    for line in text.splitlines():
        match = HEADER_KEY.match(line)
        if match:
            fields[match.group(1)] = match.group(2)

    if not fields:
        raise HassError(f"{source} has no hass-edit header: {_HEADER_HELP}")
    missing = [k for k in ("kind", "digest") if not fields.get(k)]
    if missing:
        raise HassError(
            f"{source} header is missing {', '.join(missing)}: {_HEADER_HELP}"
        )
    kind = fields["kind"]
    if kind not in KINDS:
        raise HassError(
            f"{source} header has unknown kind '{kind}'; "
            f"expected one of {', '.join(KINDS)}"
        )

    try:
        body = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise HassError(f"{source} is not valid YAML: {exc}") from None
    if not isinstance(body, dict):
        raise HassError(
            f"{source} body must be a YAML mapping, got {type(body).__name__}"
        )

    target = Target(kind=kind, ref=fields.get("ref", ""), view=fields.get("view", ""))
    if kind == "view" and not target.view:
        raise HassError(f"{source} header is missing view: {_HEADER_HELP}")
    return target, fields["digest"], body
