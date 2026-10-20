"""Check a node's firmware against the Z-Wave JS firmware update service."""

from __future__ import annotations

import click

from zwave._client import Session, node_state, print_json, run


@click.command()
@click.argument("node_id", type=int)
@click.option("--prereleases", is_flag=True, help="Include prerelease firmware")
def cli(node_id: int, prereleases: bool) -> None:
    """Show NODE_ID's installed firmware and the updates the service offers."""

    async def handler(session: Session):
        node = await node_state(session, node_id)
        result = await session.send(
            "controller.get_available_firmware_updates",
            nodeId=node_id,
            includePrereleases=prereleases,
        )
        return {
            "installed": node.get("firmwareVersion"),
            "updates": [
                {k: u.get(k) for k in ("version", "channel", "changelog")}
                for u in result.get("updates", [])
            ],
        }

    print_json(run(handler))
