"""Inspect and force priority routes between the controller and a node."""

from __future__ import annotations

import click

from zwave._client import ROUTE_SPEEDS, Session, node_state, print_json, run


@click.group()
def cli() -> None:
    """Inspect, force, or clear a node's priority routes.

    A priority route overrides the routes Z-Wave chooses automatically. `set`
    and `clear` cover both directions: controller to node, and node to
    controller (the path the node's own reports, such as physical toggles, use).
    """


@cli.command()
@click.argument("node_id", type=int)
def show(node_id: int) -> None:
    """Show the controller-to-NODE_ID route the controller uses."""

    async def handler(session: Session):
        return await session.send(
            "controller.get_priority_route", destinationNodeId=node_id
        )

    print_json(run(handler))


@cli.command("set")
@click.argument("node_id", type=int)
@click.argument("repeaters", type=int, nargs=-1)
@click.option(
    "--speed",
    type=click.Choice(list(ROUTE_SPEEDS)),
    default="100k",
    show_default=True,
    help="Route data rate; every hop must support it",
)
def set_cmd(node_id: int, repeaters: tuple[int, ...], speed: str) -> None:
    """Force both directions between the controller and NODE_ID through REPEATERS.

    Omit REPEATERS to force a direct link.
    """

    async def handler(session: Session):
        # The controller accepts routes to node IDs that do not exist.
        await node_state(session, node_id)
        fields = {"repeaters": list(repeaters), "routeSpeed": ROUTE_SPEEDS[speed]}
        to_node = await session.send(
            "controller.set_priority_route", destinationNodeId=node_id, **fields
        )
        to_controller = await session.send(
            "controller.assign_priority_suc_return_route", nodeId=node_id, **fields
        )
        return to_node.get("success"), to_controller.get("success")

    to_node, to_controller = run(handler)
    path = " -> ".join(["1", *map(str, repeaters), str(node_id)])
    click.echo(f"controller to node {path}: {'set' if to_node else 'FAILED'}")
    click.echo(f"node to controller (reverse): {'set' if to_controller else 'FAILED'}")
    if not (to_node and to_controller):
        raise SystemExit(1)


@cli.command()
@click.argument("node_id", type=int)
def clear(node_id: int) -> None:
    """Remove NODE_ID's forced routes in both directions, restoring automatic routing."""

    async def handler(session: Session):
        await node_state(session, node_id)
        to_node = await session.send(
            "controller.remove_priority_route", destinationNodeId=node_id
        )
        # Deleting drops every return route, not just the forced one, so the
        # node needs automatic ones reassigned to keep reporting reliably.
        deleted = await session.send(
            "controller.delete_suc_return_routes", nodeId=node_id
        )
        assigned = await session.send(
            "controller.assign_suc_return_routes", nodeId=node_id
        )
        return to_node.get("success"), deleted.get("success") and assigned.get(
            "success"
        )

    to_node, to_controller = run(handler)
    click.echo(f"controller to node: {'cleared' if to_node else 'FAILED'}")
    click.echo(f"node to controller: {'cleared' if to_controller else 'FAILED'}")
    if not (to_node and to_controller):
        raise SystemExit(1)
