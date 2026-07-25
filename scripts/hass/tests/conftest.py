"""Shared test fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest


class FakeWs:
    """Scriptable stand-in for ``run_ws``: routes payloads by message type."""

    def __init__(self, responses: dict[str, Any]):
        self.responses = responses
        self.sent: list[dict] = []

    async def _send(self, payload: dict) -> dict:
        self.sent.append(payload)
        result = self.responses[payload["type"]]
        if callable(result):
            result = result(payload)
        if isinstance(result, dict) and "success" in result:
            return result
        return {"success": True, "result": result}

    def run(self, handler: Callable) -> Any:
        return asyncio.run(handler(self._send))

    def payloads(self, msg_type: str) -> list[dict]:
        return [p for p in self.sent if p["type"] == msg_type]


@pytest.fixture
def fake_ws():
    return FakeWs
