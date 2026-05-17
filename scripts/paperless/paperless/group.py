"""Group management."""

from __future__ import annotations

import click

from paperless._click import HelpfulGroup
from paperless._client import get_transport, open_client, run_async


@click.group(cls=HelpfulGroup)
def cli() -> None:
    """List and manage groups."""


@cli.command("list")
def list_cmd() -> None:
    """List all groups."""

    async def _list():
        async with open_client() as p:
            groups = []
            async for g in p.groups:
                groups.append(g)
            return groups

    groups = run_async(_list())
    if not groups:
        click.echo("no groups")
        return
    for g in sorted(groups, key=lambda x: x.name or ""):
        click.echo(f"#{g.id} {g.name}")


@cli.command()
@click.argument("name")
def create(name: str) -> None:
    """Create a new group."""

    async def _create():
        transport = get_transport()
        try:
            result = await transport.post("/api/groups/", json={"name": name})
            return result
        finally:
            await transport.close()

    result = run_async(_create())
    click.echo(f"created group #{result['id']}: {name}")


@cli.command()
@click.argument("group_id", type=int)
def delete(group_id: int) -> None:
    """Delete a group by ID."""

    async def _delete():
        transport = get_transport()
        try:
            await transport.delete(f"/api/groups/{group_id}/")
        finally:
            await transport.close()

    run_async(_delete())
    click.echo(f"deleted group #{group_id}")


@cli.command()
@click.argument("group_id", type=int)
@click.option(
    "--add-user",
    "add_users",
    multiple=True,
    type=int,
    help="User ID to add to group (repeatable).",
)
@click.option(
    "--remove-user",
    "remove_users",
    multiple=True,
    type=int,
    help="User ID to remove from group (repeatable).",
)
def members(
    group_id: int, add_users: tuple[int, ...], remove_users: tuple[int, ...]
) -> None:
    """Add or remove users from a group."""
    if not add_users and not remove_users:
        # Show current members
        async def _show():
            async with open_client() as p:
                users = []
                async for u in p.users:
                    if group_id in (u.groups or []):
                        users.append(u)
                return users

        users = run_async(_show())
        if not users:
            click.echo("no members")
            return
        for u in users:
            click.echo(f"#{u.id} {u.username}")
        return

    async def _update():
        transport = get_transport()
        try:
            # Get current group members by checking each user
            users_data = await transport.get("/api/users/")
            results = (
                users_data.get("results", users_data)
                if isinstance(users_data, dict)
                else users_data
            )
            for uid in add_users:
                for user in results:
                    if user["id"] == uid:
                        current_groups = set(user.get("groups", []))
                        current_groups.add(group_id)
                        await transport.patch(
                            f"/api/users/{uid}/",
                            json={"groups": list(current_groups)},
                        )
                        break
            for uid in remove_users:
                for user in results:
                    if user["id"] == uid:
                        current_groups = set(user.get("groups", []))
                        current_groups.discard(group_id)
                        await transport.patch(
                            f"/api/users/{uid}/",
                            json={"groups": list(current_groups)},
                        )
                        break
        finally:
            await transport.close()

    run_async(_update())
    changes = []
    if add_users:
        changes.append(f"added {list(add_users)}")
    if remove_users:
        changes.append(f"removed {list(remove_users)}")
    click.echo(f"group #{group_id}: {', '.join(changes)}")
