"""Rebuild routes for individual nodes."""

from __future__ import annotations

import click

from zwave._client import Session, run


@click.command()
@click.argument("node_ids", type=int, nargs=-1, required=True)
def cli(node_ids: tuple[int, ...]) -> None:
    """Rebuild routes for NODE_IDS in order; exits non-zero if any rebuild fails.

    Rebuild a moved repeater before the nodes that should route through it.
    """

    async def handler(session: Session):
        results = {}
        for node_id in node_ids:
            result = await session.send(
                "controller.rebuild_node_routes", nodeId=node_id
            )
            results[node_id] = result.get("success", False)
        return results

    results = run(handler)
    for node_id, ok in results.items():
        click.echo(f"{node_id}: {'rebuilt' if ok else 'FAILED'}")
    if not all(results.values()):
        raise SystemExit(1)
