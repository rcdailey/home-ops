"""Show one node's health, statistics, and associations."""

from __future__ import annotations

import click

from zwave._client import Session, node_state, print_json, run
from zwave.nodes import summarize


@click.command()
@click.argument("node_id", type=int)
def cli(node_id: int) -> None:
    """Show NODE_ID's summary, radio statistics, and association groups.

    Association groups list where the node sends reports; the Lifeline group
    must target the controller (node 1) for physical changes to reach it.
    """

    async def handler(session: Session):
        node = await node_state(session, node_id)
        targets = await session.send("controller.get_all_associations", nodeId=node_id)
        groups = await session.send(
            "controller.get_all_association_groups", nodeId=node_id
        )
        associations = {}
        for endpoint, endpoint_groups in groups["groups"].items():
            linked = targets["associations"].get(str(node_id), {}).get(endpoint, {})
            for group_id, group in endpoint_groups.items():
                associations[f"{endpoint}/{group_id}"] = {
                    "label": group.get("label"),
                    "lifeline": group.get("isLifeline"),
                    "targets": [a["nodeId"] for a in linked.get(group_id, [])],
                }
        return {
            **summarize(node),
            "security": node.get("highestSecurityClass"),
            "statistics": node.get("statistics"),
            "associations": associations,
        }

    print_json(run(handler))
