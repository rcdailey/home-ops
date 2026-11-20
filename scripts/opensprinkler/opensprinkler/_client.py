"""HTTP client for the OpenSprinkler firmware API (2.2.1 series)."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, NoReturn

HOST = "192.168.2.108"

# Firmware result codes; 1 is success.
RESULT_CODES = {
    2: "unauthorized (wrong OPENSPRINKLER_PASSWORD)",
    3: "password mismatch",
    16: "required parameter missing",
    17: "value out of range",
    18: "data format error",
    19: "RF code error",
    32: "page not found",
    48: "not permitted",
    64: "upload failed",
    80: "internal error",
}


class ApiError(Exception):
    """The controller rejected a request or could not be reached."""


def die(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def _password_hash() -> str:
    password = os.environ.get("OPENSPRINKLER_PASSWORD")
    if not password:
        die("OPENSPRINKLER_PASSWORD is not set")
    return hashlib.md5(password.encode()).hexdigest()


def _encode(value: str) -> str:
    # The firmware parses program arrays (v=[...]) literally, so keep brackets and commas raw.
    return urllib.parse.quote(value, safe="[],-:")


def call(endpoint: str, params: dict[str, Any] | None = None) -> Any:
    """GET an endpoint and return parsed JSON. Raises ApiError on a non-success result."""
    query = [f"pw={_password_hash()}"]
    query += [f"{k}={_encode(str(v))}" for k, v in (params or {}).items()]
    url = f"http://{HOST}/{endpoint}?{'&'.join(query)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            body = resp.read().decode()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ApiError(f"{endpoint}: {exc}") from exc
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ApiError(f"{endpoint}: non-JSON response: {body[:200]}") from exc
    if isinstance(data, dict) and "result" in data and data["result"] != 1:
        code = data["result"]
        item = f" ({data['item']})" if data.get("item") else ""
        raise ApiError(f"{endpoint}: {RESULT_CODES.get(code, f'result {code}')}{item}")
    return data


def station_names() -> list[str]:
    """Station names, with disabled stations (which never run) suffixed ' (disabled)'."""
    jn = call("jn")
    return [
        f"{name} (disabled)" if jn["stn_dis"][i // 8] >> (i % 8) & 1 else name
        for i, name in enumerate(jn["snames"])
    ]


def resolve_station(ref: str, names: list[str]) -> int:
    """Resolve a station by 0-based index or exact (case-insensitive) name."""
    if ref.isdigit() and int(ref) < len(names):
        return int(ref)
    matches = [i for i, n in enumerate(names) if n.lower() == ref.lower()]
    if not matches:
        raise ApiError(f"no station named {ref!r}; see `station list --all`")
    return matches[0]
