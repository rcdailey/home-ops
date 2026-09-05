"""Backup domain: Volsync + CNPG backup status, Kopia repository management."""

from __future__ import annotations

import click

from hops._click import HelpfulGroup
from hops.backup_inspect import inspect_backup, list_backups
from hops.core.format import age_str, info, section, table
from hops.core.runner import kubectl_json, run


@click.group(cls=HelpfulGroup)
def cli():
    """Backup operations: status overview, Kopia repository management."""


@cli.command()
def status():
    """Backup health: Volsync sync times and CNPG scheduled backups."""
    # Volsync ReplicationSources
    vs_data = kubectl_json("replicationsources")
    vs_rows = []
    for item in vs_data.get("items", []):
        meta = item.get("metadata", {})
        ns = meta.get("namespace", "")
        name = meta.get("name", "")
        st = item.get("status", {})
        last_sync = st.get("lastSyncTime")
        sync_age = age_str(last_sync) + " ago" if last_sync else "never"
        vs_rows.append([ns, name, sync_age])
    vs_rows.sort(key=lambda r: (r[0], r[1]))
    section("Volsync")
    if vs_rows:
        table(["NAMESPACE", "NAME", "LAST SYNC"], vs_rows)
    else:
        info("No ReplicationSources found.")

    # CNPG ScheduledBackups + most recent Backup result per cluster
    sb_data = kubectl_json("scheduledbackups")
    if not sb_data.get("items"):
        section("CNPG Backups")
        info("No ScheduledBackups found.")
        return

    # Index most recent backup per cluster
    bk_data = kubectl_json("backups.postgresql.cnpg.io")
    latest: dict[str, dict] = {}
    for item in bk_data.get("items", []):
        meta = item.get("metadata", {})
        ns = meta.get("namespace", "")
        cluster = item.get("spec", {}).get("cluster", {}).get("name", "")
        key = f"{ns}/{cluster}"
        st = item.get("status", {})
        started = st.get("startedAt", "")
        if key not in latest or started > latest[key].get("started", ""):
            latest[key] = {
                "started": started,
                "phase": st.get("phase", "unknown"),
            }

    cnpg_rows = []
    for item in sb_data.get("items", []):
        meta = item.get("metadata", {})
        ns = meta.get("namespace", "")
        cluster = item.get("spec", {}).get("cluster", {}).get("name", "")
        schedule = item.get("spec", {}).get("schedule", "?")
        key = f"{ns}/{cluster}"
        bk = latest.get(key, {})
        phase = bk.get("phase", "none")
        bk_age = age_str(bk["started"]) + " ago" if bk.get("started") else "never"
        cnpg_rows.append([ns, cluster, schedule, phase, bk_age])
    cnpg_rows.sort(key=lambda r: (r[0], r[1]))
    section("CNPG Backups")
    table(["NAMESPACE", "CLUSTER", "SCHEDULE", "LAST STATUS", "LAST BACKUP"], cnpg_rows)


@cli.command("list")
@click.option(
    "-n",
    "--namespace",
    "namespaces",
    multiple=True,
    help="Include a namespace; repeat to include more than one.",
)
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(["size", "last-snapshot"]),
    default="size",
    show_default=True,
)
def list_command(namespaces: tuple[str, ...], sort_by: str):
    """List the latest Kopia backup for each source."""
    list_backups(namespaces, sort_by)


@cli.command("inspect")
@click.argument("app")
@click.option("-n", "--namespace", help="Namespace containing the ReplicationSource.")
@click.option(
    "--path", default="", help="Directory below the snapshot root to inspect."
)
@click.option("--limit", type=click.IntRange(min=1), default=30, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def inspect_command(
    app: str,
    namespace: str | None,
    path: str,
    limit: int,
    as_json: bool,
):
    """Rank contents and mounts for an app's latest Kopia backup."""
    inspect_backup(app, namespace, path, limit, as_json)


@cli.command()
@click.argument("args", nargs=-1)
def kopia(args: tuple[str, ...]):
    """Run kopia commands via the kopia pod in storage namespace.

    Pass any kopia subcommand and arguments after --.
    Example: hops backup kopia snapshot list
    """
    cmd = [
        "kubectl",
        "exec",
        "-n",
        "storage",
        "deploy/kopia",
        "--",
        "kopia",
    ] + list(args)
    result = run(cmd, timeout=60, check=False)
    if result.stdout:
        click.echo(result.stdout.rstrip())
    if result.stderr:
        click.echo(result.stderr.rstrip())
    if result.returncode != 0:
        raise SystemExit(result.returncode)
