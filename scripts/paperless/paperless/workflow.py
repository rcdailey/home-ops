"""Workflow management."""

from __future__ import annotations


import click

from paperless._click import HelpfulGroup
from paperless._client import get_transport, open_client, run_async


@click.group(cls=HelpfulGroup)
def cli() -> None:
    """List, inspect, and manage workflows."""


@cli.command("list")
def list_cmd() -> None:
    """List all workflows."""

    async def _list():
        async with open_client() as p:
            return await p.workflows.as_list()

    items = run_async(_list())
    if not items:
        click.echo("no workflows")
        return
    for wf in items:
        status = "enabled" if wf.enabled else "disabled"
        click.echo(f"#{wf.id} {wf.name} ({status})")


@cli.command()
@click.argument("workflow_id", type=int)
def show(workflow_id: int) -> None:
    """Show workflow details including triggers and actions."""

    async def _show():
        async with open_client() as p:
            wf = await p.workflows(workflow_id)
            triggers = []
            for tid in wf.triggers if hasattr(wf, "triggers") and wf.triggers else []:
                try:
                    t = await p.workflows.triggers(tid)
                    triggers.append(t)
                except Exception:
                    triggers.append(tid)
            actions = []
            for aid in wf.actions if hasattr(wf, "actions") and wf.actions else []:
                try:
                    a = await p.workflows.actions(aid)
                    actions.append(a)
                except Exception:
                    actions.append(aid)
            return wf, triggers, actions

    wf, triggers, actions = run_async(_show())
    status = "enabled" if wf.enabled else "disabled"
    click.echo(f"workflow #{wf.id}: {wf.name} ({status})")

    if triggers:
        click.echo("triggers:")
        for t in triggers:
            if hasattr(t, "type"):
                parts = [f"  type: {t.type.name}"]
                if hasattr(t, "sources") and t.sources:
                    src_names = [s.name for s in t.sources]
                    parts.append(f"sources={src_names}")
                if hasattr(t, "filter_filename") and t.filter_filename:
                    parts.append(f"filename={t.filter_filename}")
                if hasattr(t, "filter_path") and t.filter_path:
                    parts.append(f"path={t.filter_path}")
                if hasattr(t, "filter_has_tags") and t.filter_has_tags:
                    parts.append(f"has_tags={t.filter_has_tags}")
                click.echo(", ".join(parts))
            else:
                click.echo(f"  trigger #{t}")

    if actions:
        click.echo("actions:")
        for a in actions:
            if hasattr(a, "type"):
                parts = [f"  type: {a.type.name}"]
                if hasattr(a, "assign_owner") and a.assign_owner:
                    parts.append(f"owner={a.assign_owner}")
                if hasattr(a, "assign_tags") and a.assign_tags:
                    parts.append(f"tags={a.assign_tags}")
                if hasattr(a, "assign_correspondent") and a.assign_correspondent:
                    parts.append(f"correspondent={a.assign_correspondent}")
                if hasattr(a, "assign_document_type") and a.assign_document_type:
                    parts.append(f"type={a.assign_document_type}")
                if hasattr(a, "assign_view_users") and a.assign_view_users:
                    parts.append(f"view_users={a.assign_view_users}")
                if hasattr(a, "assign_view_groups") and a.assign_view_groups:
                    parts.append(f"view_groups={a.assign_view_groups}")
                if hasattr(a, "assign_change_users") and a.assign_change_users:
                    parts.append(f"change_users={a.assign_change_users}")
                if hasattr(a, "assign_change_groups") and a.assign_change_groups:
                    parts.append(f"change_groups={a.assign_change_groups}")
                click.echo(", ".join(parts))
            else:
                click.echo(f"  action #{a}")


@cli.command()
@click.argument("name")
@click.option(
    "--trigger-type",
    type=click.Choice(
        ["consumption", "document_added", "document_updated", "scheduled"]
    ),
    required=True,
    help="Trigger type.",
)
@click.option(
    "--source",
    "sources",
    multiple=True,
    type=click.Choice(["consume_folder", "api_upload", "mail_fetch", "web_ui"]),
    help="Source filter (repeatable, consumption/document_added only).",
)
@click.option(
    "--filter-tag", "filter_tags", multiple=True, type=int, help="Filter by tag ID."
)
@click.option("--filter-path", default=None, help="Filter by file path pattern.")
@click.option("--assign-owner", default=None, type=int, help="Assign owner user ID.")
@click.option(
    "--assign-view-group",
    "assign_view_groups",
    multiple=True,
    type=int,
    help="Grant view to group ID (repeatable).",
)
@click.option(
    "--assign-change-group",
    "assign_change_groups",
    multiple=True,
    type=int,
    help="Grant edit to group ID (repeatable).",
)
@click.option(
    "--assign-view-user",
    "assign_view_users",
    multiple=True,
    type=int,
    help="Grant view to user ID (repeatable).",
)
@click.option(
    "--assign-change-user",
    "assign_change_users",
    multiple=True,
    type=int,
    help="Grant edit to user ID (repeatable).",
)
@click.option(
    "--assign-tag", "assign_tags", multiple=True, type=int, help="Assign tag ID."
)
@click.option("--assign-type", default=None, type=int, help="Assign document type ID.")
@click.option(
    "--assign-correspondent", default=None, type=int, help="Assign correspondent ID."
)
def create(
    name: str,
    trigger_type: str,
    sources: tuple[str, ...],
    filter_tags: tuple[int, ...],
    filter_path: str | None,
    assign_owner: int | None,
    assign_view_groups: tuple[int, ...],
    assign_change_groups: tuple[int, ...],
    assign_view_users: tuple[int, ...],
    assign_change_users: tuple[int, ...],
    assign_tags: tuple[int, ...],
    assign_type: int | None,
    assign_correspondent: int | None,
) -> None:
    """Create a workflow with a trigger and action."""
    trigger_type_map = {
        "consumption": 1,
        "document_added": 2,
        "document_updated": 3,
        "scheduled": 4,
    }
    source_map = {
        "consume_folder": 1,
        "api_upload": 2,
        "mail_fetch": 3,
        "web_ui": 4,
    }

    async def _create():
        transport = get_transport()
        try:
            # Build trigger
            trigger: dict = {"type": trigger_type_map[trigger_type]}
            if sources:
                trigger["sources"] = [source_map[s] for s in sources]
            if filter_tags:
                trigger["filter_has_tags"] = list(filter_tags)
            if filter_path:
                trigger["filter_path"] = filter_path

            # Build action
            action: dict = {"type": 1}  # ASSIGNMENT
            if assign_owner is not None:
                action["assign_owner"] = assign_owner
            if assign_view_groups:
                action["assign_view_groups"] = list(assign_view_groups)
            if assign_change_groups:
                action["assign_change_groups"] = list(assign_change_groups)
            if assign_view_users:
                action["assign_view_users"] = list(assign_view_users)
            if assign_change_users:
                action["assign_change_users"] = list(assign_change_users)
            if assign_tags:
                action["assign_tags"] = list(assign_tags)
            if assign_type is not None:
                action["assign_document_type"] = assign_type
            if assign_correspondent is not None:
                action["assign_correspondent"] = assign_correspondent

            payload = {
                "name": name,
                "enabled": True,
                "triggers": [trigger],
                "actions": [action],
            }
            result = await transport.post("/api/workflows/", json=payload)
            return result
        finally:
            await transport.close()

    result = run_async(_create())
    click.echo(f"created workflow #{result['id']}: {name}")


@cli.command()
@click.argument("workflow_id", type=int)
def delete(workflow_id: int) -> None:
    """Delete a workflow by ID."""

    async def _delete():
        transport = get_transport()
        try:
            await transport.delete(f"/api/workflows/{workflow_id}/")
        finally:
            await transport.close()

    run_async(_delete())
    click.echo(f"deleted workflow #{workflow_id}")


@cli.command()
@click.argument("workflow_id", type=int)
def enable(workflow_id: int) -> None:
    """Enable a workflow."""

    async def _enable():
        transport = get_transport()
        try:
            await transport.patch(
                f"/api/workflows/{workflow_id}/", json={"enabled": True}
            )
        finally:
            await transport.close()

    run_async(_enable())
    click.echo(f"enabled workflow #{workflow_id}")


@cli.command()
@click.argument("workflow_id", type=int)
def disable(workflow_id: int) -> None:
    """Disable a workflow."""

    async def _disable():
        transport = get_transport()
        try:
            await transport.patch(
                f"/api/workflows/{workflow_id}/", json={"enabled": False}
            )
        finally:
            await transport.close()

    run_async(_disable())
    click.echo(f"disabled workflow #{workflow_id}")
