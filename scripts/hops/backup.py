"""Backup domain: Kopia repository management."""

from __future__ import annotations

import click

from hops._runner import run


@click.group()
def cli():
    """Backup operations: Kopia repository management."""


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
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip())
    if result.returncode != 0:
        raise SystemExit(result.returncode)
