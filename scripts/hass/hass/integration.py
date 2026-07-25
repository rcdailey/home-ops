"""Triage integration config entries and pending discovery flows."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

import click

from hass._client import run_ws, ws_error
from hass._errors import die

_BAD_STATES = ("setup_error", "setup_retry", "migration_error", "failed_unload")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


async def _registry_counts(send) -> tuple[dict[str, int], dict[str, int]]:
    """Return device and entity counts keyed by config entry_id."""
    devices = (await send({"type": "config/device_registry/list"})).get("result", [])
    entities = (await send({"type": "config/entity_registry/list"})).get("result", [])
    dev_counts: dict[str, int] = defaultdict(int)
    for d in devices:
        for entry_id in d.get("config_entries", []):
            dev_counts[entry_id] += 1
    ent_counts: dict[str, int] = defaultdict(int)
    for e in entities:
        if e.get("config_entry_id"):
            ent_counts[e["config_entry_id"]] += 1
    return dev_counts, ent_counts


async def _entries(send) -> list[dict]:
    msg = await send({"type": "config_entries/get"})
    if not msg.get("success"):
        die(f"Error: {ws_error(msg)}")
    return msg["result"]


def _entry_line(entry: dict, devs: int, ents: int) -> str:
    parts = [f"{entry['domain']}: {entry.get('title') or '(untitled)'}"]
    state = entry.get("state", "?")
    if entry.get("source") == "ignore":
        parts.append("ignored")
    elif state != "loaded":
        parts.append(state)
        if entry.get("disabled_by"):
            parts.append(f"disabled_by={entry['disabled_by']}")
        if entry.get("reason"):
            parts.append(f"reason={entry['reason']}")
    parts.append(f"devices={devs} entities={ents}")
    parts.append(f"src={entry.get('source', '?')}")
    return " | ".join(parts)


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Inspect integrations, config entries, and discovery flows."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_cmd)


@cli.command("list")
@click.argument("domain", required=False)
@click.option("--all", "show_all", is_flag=True, help="Include healthy entries")
@click.option("--ignored", "show_ignored", is_flag=True, help="Include ignored entries")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def list_cmd(
    domain: str | None, show_all: bool, show_ignored: bool, as_json: bool
) -> None:
    """List config entries with state and device/entity counts.

    Without a DOMAIN filter or --all, only problem entries are listed
    (non-loaded, disabled, or errored) plus a per-state summary.
    """

    async def handler(send):
        entries = await _entries(send)
        dev_counts, ent_counts = await _registry_counts(send)

        if domain:
            entries = [
                e for e in entries if domain.casefold() in e["domain"].casefold()
            ]
            if not entries:
                click.echo(f"(no config entries matching '{domain}')")
                return

        shown = entries
        if not (show_ignored or domain):
            shown = [e for e in shown if e.get("source") != "ignore"]
        if not (show_all or domain):
            shown = [e for e in shown if e.get("state") != "loaded"]

        if as_json:
            click.echo(json.dumps(shown, indent=2))
            return

        states = Counter(e.get("state", "?") for e in entries)
        ignored = sum(1 for e in entries if e.get("source") == "ignore")
        summary = " ".join(f"{k}={v}" for k, v in sorted(states.items()))
        click.echo(f"{len(entries)} config entries: {summary} ignored={ignored}")

        def line(entry: dict) -> str:
            eid = entry["entry_id"]
            return _entry_line(entry, dev_counts[eid], ent_counts[eid])

        broken = [e for e in shown if e.get("state") in _BAD_STATES]
        if broken:
            click.echo(f"{len(broken)} entry(s) in an error state:")
            for e in broken:
                click.echo(f"  {line(e)}")

        broken_ids = {e["entry_id"] for e in broken}
        rest = [e for e in shown if e["entry_id"] not in broken_ids]
        for e in sorted(rest, key=lambda x: (x["domain"], x.get("title") or "")):
            click.echo(line(e))
        if not shown:
            click.echo("nothing to report")
        elif not (show_all or domain):
            click.echo("(use --all for loaded entries, --ignored for ignored ones)")

    run_ws(handler)


def _flow_title(flow: dict) -> str:
    ctx = flow.get("context", {})
    ph = ctx.get("title_placeholders") or {}
    return (
        flow.get("title")
        or ph.get("name")
        or ph.get("host")
        or ctx.get("unique_id")
        or flow.get("flow_id", "")
    )


def _duplicates(flow: dict, entries: list[dict]) -> list[str]:
    """Existing config entries that appear to cover the same device."""
    title = _slug(_flow_title(flow))
    if not title:
        return []
    hits = []
    for e in entries:
        if e["domain"] == flow.get("handler"):
            continue
        etitle = _slug(e.get("title") or "")
        if not etitle:
            continue
        if etitle == title or etitle in title or title in etitle:
            state = "ignored" if e.get("source") == "ignore" else e.get("state", "?")
            hits.append(f"{e['domain']} '{e.get('title')}' ({state})")
    return hits


async def _flows(send) -> list[dict]:
    msg = await send({"type": "config_entries/flow/progress"})
    if not msg.get("success"):
        die(f"Error: {ws_error(msg)}")
    return msg["result"]


@cli.command("discovered")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output")
def discovered_cmd(as_json: bool) -> None:
    """List pending discovery flows, flagging ones an existing entry covers."""

    async def handler(send):
        flows = await _flows(send)
        if as_json:
            click.echo(json.dumps(flows, indent=2))
            return
        if not flows:
            click.echo("(no pending discovery flows)")
            return
        entries = await _entries(send)
        for flow in flows:
            handler_domain = flow.get("handler", "?")
            title = _flow_title(flow)
            source = flow.get("context", {}).get("source", "?")
            selector = f"{handler_domain}/{_slug(title)}"
            click.echo(
                f"{selector} | {title} | via {source} | step={flow.get('step_id', '?')}"
            )
            for dup in _duplicates(flow, entries):
                click.echo(f"  duplicate of {dup}")
        click.echo(
            f"{len(flows)} pending; dismiss with: hass.sh integration ignore SELECTOR"
        )

    run_ws(handler)


@cli.command("ignore")
@click.argument("selector")
def ignore_cmd(selector: str) -> None:
    """Dismiss a discovery flow by domain/slug, title substring, or flow id."""

    async def handler(send):
        flows = await _flows(send)
        if not flows:
            die("no pending discovery flows")
        want = selector.casefold()
        matches = [
            f
            for f in flows
            if f.get("flow_id") == selector
            or want in f"{f.get('handler', '')}/{_slug(_flow_title(f))}"
            or want in _flow_title(f).casefold()
        ]
        if not matches:
            known = ", ".join(
                f"{f.get('handler')}/{_slug(_flow_title(f))}" for f in flows
            )
            die(f"no discovery flow matching '{selector}'; pending: {known}")
        if len(matches) > 1:
            found = ", ".join(
                f"{f.get('handler')}/{_slug(_flow_title(f))}" for f in matches
            )
            die(f"ambiguous '{selector}': {found}")

        flow = matches[0]
        title = _flow_title(flow)
        msg = await send(
            {
                "type": "config_entries/ignore_flow",
                "flow_id": flow["flow_id"],
                "title": title,
            }
        )
        if not msg.get("success"):
            die(f"Failed: {ws_error(msg)}")
        click.echo(f"ignored {flow.get('handler')} discovery '{title}'")

    run_ws(handler)
