"""Pull, edit, and push automations, scripts, and dashboard views as YAML files."""

from __future__ import annotations

import difflib
import json
from pathlib import Path

import click
import yaml

from hass import _lovelace as lv
from hass import _target as tg
from hass._errors import HassError, die


def _diff(old, new, label: str) -> str:
    """Unified YAML diff between two configs."""
    lines = difflib.unified_diff(
        lv.dump(old, as_json=False).splitlines(),
        lv.dump(new, as_json=False).splitlines(),
        fromfile=f"{label} (upstream)",
        tofile=f"{label} (file)",
        lineterm="",
        n=2,
    )
    return "\n".join(lines)


@click.group()
def cli() -> None:
    """Edit automations, scripts, and dashboard views as local YAML files."""


@cli.group("pull")
def pull_group() -> None:
    """Write an object to a local YAML file that `edit push` can send back."""


def _out_option(func):
    return click.option(
        "--out", "-o", "out", help=f"Output file (default: {tg.EDIT_DIR}/<slug>.yaml)"
    )(func)


def _write(target: tg.Target, out: str | None) -> None:
    config = target.fetch()
    if config is None:
        raise HassError(f"no such {target.label}")
    path = Path(out) if out else tg.EDIT_DIR / f"{target.slug}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tg.render(target, config, path))
    click.echo(f"pulled {target.label} -> {path}")


@pull_group.command("automation")
@click.argument("identifier")
@_out_option
def pull_automation(identifier: str, out: str | None) -> None:
    """Pull an automation by entity_id or UUID."""
    _run(
        lambda: _write(
            tg.Target("automation", tg.resolve_automation_id(identifier)), out
        )
    )


@pull_group.command("script")
@click.argument("identifier")
@_out_option
def pull_script(identifier: str, out: str | None) -> None:
    """Pull a script by entity_id or slug."""
    _run(lambda: _write(tg.Target("script", tg.resolve_script_slug(identifier)), out))


@pull_group.command("view")
@click.argument("url_path", required=False)
@click.option("--view", "view_sel", required=True, help="View (title, path, or #index)")
@_out_option
def pull_view(url_path: str | None, view_sel: str, out: str | None) -> None:
    """Pull one Lovelace view (omit URL_PATH for Overview)."""
    _run(lambda: _write(tg.Target("view", url_path or "", view_sel), out))


@cli.command("push")
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("--dry-run", is_flag=True, help="Show the diff, do not write")
@click.option("--force", is_flag=True, help="Push even though upstream drifted")
@click.option("--json", "as_json", is_flag=True, help="Report as JSON")
def push_cmd(file: str, dry_run: bool, force: bool, as_json: bool) -> None:
    """Send a pulled file back to Home Assistant."""

    def go() -> None:
        target, pulled_digest, body = tg.parse(Path(file).read_text(), file)
        upstream = target.fetch()
        if upstream is None:
            raise HassError(
                f"{target.label} no longer exists; recreate it with `hass edit create`"
            )

        drifted = tg.digest(upstream) != pulled_digest
        if drifted and not force:
            raise HassError(
                f"{target.label} changed upstream since it was pulled; "
                f"re-pull and reapply your edit, or push again with --force\n"
                + _diff(upstream, body, target.label)
            )

        diff = _diff(upstream, body, target.label)
        if not diff:
            _report(
                as_json,
                "noop",
                target,
                f"no changes: {target.label} already matches {file}",
            )
            return
        if dry_run:
            _report(
                as_json,
                "dry-run",
                target,
                f"dry-run: would update {target.label}",
                diff,
            )
            return

        target.push(body)
        stored = target.fetch()
        normalized = _diff(body, stored, target.label) if stored is not None else ""
        _report(as_json, "pushed", target, f"pushed {target.label}", diff, normalized)

    _run(go)


def _report(
    as_json: bool,
    status: str,
    target: tg.Target,
    message: str,
    diff: str = "",
    normalized: str = "",
) -> None:
    """Print a push outcome, terse by default."""
    if as_json:
        click.echo(
            json.dumps(
                {
                    "status": status,
                    "target": target.label,
                    "diff": diff,
                    "normalized": normalized,
                },
                indent=2,
            )
        )
        return
    click.echo(message)
    if diff:
        click.echo(diff)
    if normalized:
        click.echo("note: HA rewrote the stored config (file vs stored):")
        click.echo(normalized)


@cli.command("create")
@click.argument("kind", type=click.Choice(["automation", "script"]))
@click.argument("ref")
@click.option("--file", "-f", "src", required=True, help="Config YAML/JSON ('-' stdin)")
@click.option("--dry-run", is_flag=True, help="Validate and report, do not write")
def create_cmd(kind: str, ref: str, src: str, dry_run: bool) -> None:
    """Create a new automation (REF = new UUID) or script (REF = slug) from a file."""

    def go() -> None:
        text = (
            click.get_text_stream("stdin").read()
            if src == "-"
            else Path(src).read_text()
        )
        try:
            body = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise HassError(f"{src} is not valid YAML/JSON: {exc}") from None
        if not isinstance(body, dict):
            raise HassError(f"{src} must contain a YAML/JSON mapping")
        target = tg.Target(kind, ref)
        if target.fetch() is not None:
            raise HassError(
                f"{target.label} already exists; use `hass edit pull`/`push`"
            )
        if dry_run:
            click.echo(f"dry-run: would create {target.label}")
            click.echo(lv.dump(body, as_json=False))
            return
        target.push(body)
        click.echo(f"created {target.label}")

    _run(go)


@cli.command("delete")
@click.argument("kind", type=click.Choice(["automation", "script"]))
@click.argument("identifier")
def delete_cmd(kind: str, identifier: str) -> None:
    """Delete an automation or script."""

    def go() -> None:
        ref = (
            tg.resolve_automation_id(identifier)
            if kind == "automation"
            else tg.resolve_script_slug(identifier)
        )
        target = tg.Target(kind, ref)
        config = target.fetch()
        if config is None:
            raise HassError(f"no such {target.label}")
        target.delete()
        click.echo(f"deleted {target.label} ('{config.get('alias', '')}')")

    _run(go)


def _run(action) -> None:
    """Run an action, converting domain errors into a clean exit."""
    try:
        action()
    except HassError as exc:
        die(str(exc))
    except OSError as exc:
        die(str(exc))
