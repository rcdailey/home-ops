"""Port-forwarded WebSocket session to the Z-Wave JS server."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, contextmanager
from itertools import count
from typing import Any, NoReturn

import websockets

NAMESPACE = "home"
SERVICE = "svc/zwave-js-ui"
SERVER_PORT = 3000

NODE_STATUS = {0: "unknown", 1: "asleep", 2: "awake", 3: "dead", 4: "alive"}
ROUTE_SPEEDS = {"9.6k": 1, "40k": 2, "100k": 3}


class ZwaveError(Exception):
    """A server command failed or the server could not be reached."""


def die(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


@contextmanager
def _port_forward():
    """Yield a local port forwarded to the server; the forward ends with the block."""
    proc = subprocess.Popen(
        ["kubectl", "-n", NAMESPACE, "port-forward", SERVICE, f":{SERVER_PORT}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = proc.stdout.readline() if proc.stdout else ""
        match = re.search(r"127\.0\.0\.1:(\d+)", line)
        if not match:
            err = proc.stderr.read() if proc.stderr else ""
            raise ZwaveError(f"port-forward failed: {(line + err).strip()}")
        yield int(match.group(1))
    finally:
        proc.terminate()
        proc.wait()


class Session:
    """One server connection with the newest API schema negotiated.

    Responses and events share the socket; `send` skips events until its own
    result arrives, so use `events` only after the commands you need.
    """

    def __init__(self, ws: Any):
        self._ws = ws
        self._ids = count()

    async def send(self, command: str, **fields: Any) -> dict:
        msg_id = str(next(self._ids))
        await self._ws.send(
            json.dumps({**fields, "command": command, "messageId": msg_id})
        )
        while True:
            msg = json.loads(await self._ws.recv())
            if msg.get("type") == "result" and msg.get("messageId") == msg_id:
                break
        if not msg.get("success"):
            detail = msg.get("errorCode", "error")
            if msg.get("message"):
                detail += f": {msg['message']}"
            raise ZwaveError(f"{command}: {detail}")
        return msg.get("result") or {}

    async def events(self) -> AsyncIterator[dict]:
        while True:
            msg = json.loads(await self._ws.recv())
            if msg.get("type") == "event":
                yield msg["event"]


@asynccontextmanager
async def _session() -> AsyncIterator[Session]:
    with _port_forward() as port:
        async with websockets.connect(f"ws://127.0.0.1:{port}", max_size=None) as ws:
            version = json.loads(await ws.recv())
            session = Session(ws)
            await session.send(
                "set_api_schema", schemaVersion=version["maxSchemaVersion"]
            )
            yield session


def run(handler: Callable[[Session], Awaitable[Any]]) -> Any:
    """Run an async handler with a session; report failures as a clean exit."""

    async def main():
        async with _session() as session:
            return await handler(session)

    try:
        return asyncio.run(main())
    except (ZwaveError, OSError, websockets.WebSocketException) as exc:
        die(str(exc))


async def node_state(session: Session, node_id: int) -> dict:
    """Full state of one node; requires a session that has not started listening."""
    state = await session.send("start_listening")
    for node in state["state"]["nodes"]:
        if node["nodeId"] == node_id:
            return node
    raise ZwaveError(f"node {node_id} not found")


def print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))
