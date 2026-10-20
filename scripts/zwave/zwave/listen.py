"""Watch a node's live events."""

from __future__ import annotations

import asyncio
import time

import click

from zwave._client import Session, run


@click.command()
@click.argument("node_id", type=int)
@click.option(
    "-s", "--seconds", type=int, default=60, show_default=True, help="Listen time"
)
def cli(node_id: int, seconds: int) -> None:
    """Print NODE_ID's events (value changes, notifications) for a fixed time.

    Use it to prove whether physical actions reach the controller: no
    "value updated" lines after a toggle means the report never arrived.
    Exits non-zero when no value event arrived.
    """

    async def handler(session: Session):
        await session.send("start_listening")
        seen = 0
        events = session.events()
        deadline = time.monotonic() + seconds
        while (left := deadline - time.monotonic()) > 0:
            try:
                event = await asyncio.wait_for(anext(events), left)
            except TimeoutError:
                break
            if (
                event.get("nodeId") != node_id
                or event.get("event") == "statistics updated"
            ):
                continue
            args = event.get("args") or {}
            stamp = time.strftime("%H:%M:%S")
            click.echo(
                f"{stamp} {event['event']}: {args.get('property')} "
                f"{args.get('prevValue')!r} -> {args.get('newValue', args.get('value'))!r}",
            )
            seen += 1
        return seen

    click.echo(f"listening to node {node_id} for {seconds}s", err=True)
    if not run(handler):
        click.echo("no events", err=True)
        raise SystemExit(1)
