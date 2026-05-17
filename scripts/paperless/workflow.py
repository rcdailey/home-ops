"""Workflow inspection."""

from __future__ import annotations

import click

from paperless._click import HelpfulGroup
from paperless._client import open_client, run_async


@click.group(cls=HelpfulGroup)
def cli() -> None:
    """List and inspect workflows."""


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
                parts = [f"  type: {t.type}"]
                if hasattr(t, "filter_filename") and t.filter_filename:
                    parts.append(f"filename={t.filter_filename}")
                if hasattr(t, "filter_path") and t.filter_path:
                    parts.append(f"path={t.filter_path}")
                click.echo(", ".join(parts))
            else:
                click.echo(f"  trigger #{t}")

    if actions:
        click.echo("actions:")
        for a in actions:
            if hasattr(a, "type"):
                parts = [f"  type: {a.type}"]
                if hasattr(a, "assign_tags") and a.assign_tags:
                    parts.append(f"tags={a.assign_tags}")
                if hasattr(a, "assign_correspondent") and a.assign_correspondent:
                    parts.append(f"correspondent={a.assign_correspondent}")
                if hasattr(a, "assign_document_type") and a.assign_document_type:
                    parts.append(f"type={a.assign_document_type}")
                click.echo(", ".join(parts))
            else:
                click.echo(f"  action #{a}")
