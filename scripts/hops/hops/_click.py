"""Custom Click classes that show full help on usage errors."""

from __future__ import annotations

import importlib
import pkgutil

import click


class HelpfulGroup(click.Group):
    """Click group that appends the failing command's help to usage errors."""

    def invoke(self, ctx: click.Context) -> None:
        try:
            return super().invoke(ctx)
        except click.UsageError as exc:
            if exc.ctx is not None:
                click.echo(exc.format_message(), err=True)
                click.echo("", err=True)
                click.echo(exc.ctx.get_help(), err=True)
            else:
                click.echo(exc.format_message(), err=True)
            raise SystemExit(exc.exit_code) from None


class AutoGroup(HelpfulGroup):
    """Click group that discovers its subcommands by importing sibling modules.

    On first command lookup every non-private module of ``package`` is
    imported. A module exposing its own ``cli`` command is registered under
    the module name; modules that instead decorate this group with
    ``@cli.command`` register themselves as a side effect of the import.
    That side effect is why the imports live here rather than at the top of
    each package's ``__init__``, where they would be unreferenced names.

    A module that fails to import (missing optional dependency) is skipped
    so the rest of the CLI stays usable.
    """

    def __init__(self, *args, package: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.package = package
        self._loaded = False

    def _load_plugins(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        pkg = importlib.import_module(self.package)
        for info in pkgutil.iter_modules(pkg.__path__):
            if info.name.startswith("_"):
                continue
            try:
                mod = importlib.import_module(f"{self.package}.{info.name}")
            except ImportError:
                continue
            cmd = getattr(mod, "cli", None)
            if isinstance(cmd, click.Command) and cmd is not self:
                self.add_command(cmd, info.name)

    def list_commands(self, ctx):
        self._load_plugins()
        return super().list_commands(ctx)

    def get_command(self, ctx, cmd_name):
        self._load_plugins()
        return super().get_command(ctx, cmd_name)
