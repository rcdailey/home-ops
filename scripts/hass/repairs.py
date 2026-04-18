"""List and dismiss Home Assistant repair issues."""

from __future__ import annotations

import click

from hass._client import die, run_ws, ws_error


def _description(key: str, placeholders: dict, issue_id: str) -> str:
    name = placeholders.get("name", "")
    entity = placeholders.get("entity_id", "")
    replacement = placeholders.get("replacement_entity_id", "")
    service = placeholders.get("service", "")

    if key == "service_not_found" and name and service:
        return f"{name}: unknown service {service}"
    if key == "deprecated_sensor" and entity and replacement:
        return f"Deprecated {entity} (replace with {replacement})"
    if key == "deprecated_sensor" and entity:
        return f"Deprecated {entity}"
    if name:
        return f"{name} ({key})"
    if entity:
        return f"{entity} ({key})"
    return issue_id


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """List or dismiss HA repair issues."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_cmd)


@cli.command("list")
def list_cmd() -> None:
    """List active (non-dismissed) repairs."""

    async def handler(send):
        msg = await send({"type": "repairs/list_issues"})
        issues = [
            i for i in msg.get("result", {}).get("issues", []) if not i.get("ignored")
        ]
        if not issues:
            click.echo("(no repairs)")
            return
        for i in issues:
            sev = i["severity"].upper()
            domain = i["domain"]
            desc = _description(
                i.get("translation_key", ""),
                i.get("translation_placeholders", {}),
                i["issue_id"],
            )
            click.echo(f"{sev:8s} {domain:20s} {desc}")

    run_ws(handler)


@cli.command("dismiss")
@click.argument("issue_id")
def dismiss_cmd(issue_id: str) -> None:
    """Dismiss a repair by domain/id or substring match."""

    async def handler(send):
        parts = issue_id.split("/", 1)
        if len(parts) == 2:
            domain, iid = parts
        else:
            msg = await send({"type": "repairs/list_issues"})
            issues = msg.get("result", {}).get("issues", [])
            matches = [i for i in issues if issue_id in i["issue_id"]]
            if not matches:
                die(f"No repair matching: {issue_id}")
            if len(matches) > 1:
                lines = ["Ambiguous, multiple matches:"]
                for m in matches:
                    lines.append(f"  {m['domain']}/{m['issue_id']}")
                die("\n".join(lines))
            domain = matches[0]["domain"]
            iid = matches[0]["issue_id"]

        msg = await send(
            {
                "type": "repairs/ignore_issue",
                "domain": domain,
                "issue_id": iid,
                "ignore": True,
            }
        )
        if msg.get("success"):
            click.echo(f"Dismissed: {domain}/{iid}")
        else:
            die(f"Failed: {ws_error(msg)}")

    run_ws(handler)
