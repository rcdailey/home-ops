"""User management."""

from __future__ import annotations

import click

from paperless._click import HelpfulGroup
from paperless._client import get_transport, open_client, run_async


@click.group(cls=HelpfulGroup)
def cli() -> None:
    """List and manage users."""


@cli.command("list")
def list_cmd() -> None:
    """List all users."""

    async def _list():
        async with open_client() as p:
            users = []
            async for u in p.users:
                users.append(u)
            return users

    users = run_async(_list())
    if not users:
        click.echo("no users")
        return
    for u in sorted(users, key=lambda x: x.username or ""):
        groups = u.groups or []
        parts = [f"#{u.id} {u.username}"]
        if u.first_name or u.last_name:
            parts.append(f"({u.first_name or ''} {u.last_name or ''}".strip() + ")")
        if u.is_superuser:
            parts.append("superuser")
        if groups:
            parts.append(f"groups={groups}")
        click.echo(" | ".join(parts))


@cli.command()
@click.argument("username")
@click.option("--email", default=None, help="Email address.")
@click.option("--first-name", default=None, help="First name.")
@click.option("--last-name", default=None, help="Last name.")
@click.option("--superuser", is_flag=True, help="Grant superuser status.")
@click.option(
    "--group", "group_ids", multiple=True, type=int, help="Group ID (repeatable)."
)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def create(
    username: str,
    email: str | None,
    first_name: str | None,
    last_name: str | None,
    superuser: bool,
    group_ids: tuple[int, ...],
    password: str,
) -> None:
    """Create a new user."""

    async def _create():
        transport = get_transport()
        try:
            payload: dict = {
                "username": username,
                "password": password,
                "is_active": True,
                "is_staff": True,
                "is_superuser": superuser,
            }
            if email:
                payload["email"] = email
            if first_name:
                payload["first_name"] = first_name
            if last_name:
                payload["last_name"] = last_name
            if group_ids:
                payload["groups"] = list(group_ids)
            result = await transport.post("/api/users/", json=payload)
            return result
        finally:
            await transport.close()

    result = run_async(_create())
    click.echo(f"created user #{result['id']}: {username}")


@cli.command()
@click.argument("user_id", type=int)
def delete(user_id: int) -> None:
    """Delete a user by ID."""

    async def _delete():
        transport = get_transport()
        try:
            await transport.delete(f"/api/users/{user_id}/")
        finally:
            await transport.close()

    run_async(_delete())
    click.echo(f"deleted user #{user_id}")
