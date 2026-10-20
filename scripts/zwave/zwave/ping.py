"""Ping nodes."""

from __future__ import annotations

import click

from zwave._client import Session, run


@click.command()
@click.argument("node_ids", type=int, nargs=-1, required=True)
def cli(node_ids: tuple[int, ...]) -> None:
    """Ping NODE_IDS; exits non-zero if any node does not respond."""

    async def handler(session: Session):
        results = {}
        for node_id in node_ids:
            result = await session.send("node.ping", nodeId=node_id)
            results[node_id] = result.get("responded", False)
        return results

    results = run(handler)
    for node_id, responded in results.items():
        click.echo(f"{node_id}: {'responded' if responded else 'NO RESPONSE'}")
    if not all(results.values()):
        raise SystemExit(1)
