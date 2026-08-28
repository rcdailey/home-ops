"""Custom Click groups with compact recursive help."""

from __future__ import annotations

import importlib
import pkgutil

import click


class HelpfulGroup(click.Group):
    """Click group with compact recursive help and useful usage errors."""

    def format_help(
        self,
        ctx: click.Context,
        formatter: click.HelpFormatter,
    ) -> None:
        """Render every leaf command from Click's command metadata."""
        prefix = _context_prefix(ctx)
        lines = _command_lines(self, ctx, prefix)
        formatter.write("\n".join(lines))
        formatter.write("\n")

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


def _context_prefix(ctx: click.Context) -> tuple[str, ...]:
    """Return the current command path without the root executable."""
    names = []
    current = ctx
    while current.parent is not None:
        if current.info_name:
            names.append(current.info_name)
        current = current.parent
    return tuple(reversed(names))


def _command_lines(
    group: click.Group,
    ctx: click.Context,
    prefix: tuple[str, ...],
) -> list[str]:
    """Return compact signatures and summaries for a command tree."""
    lines = []
    for name in group.list_commands(ctx):
        command = group.get_command(ctx, name)
        if command is None or command.hidden:
            continue
        child_ctx = click.Context(command, info_name=name, parent=ctx)
        path = (*prefix, name)
        if isinstance(command, click.Group):
            lines.extend(_command_lines(command, child_ctx, path))
            continue
        signature = _signature(command, child_ctx, path)
        summary = _summary(command)
        lines.append(f"{signature}  {summary}" if summary else signature)
    return lines


def _signature(
    command: click.Command,
    ctx: click.Context,
    path: tuple[str, ...],
) -> str:
    """Build a compact command signature from Click parameters."""
    parts = [" ".join(path)]
    help_option = command.get_help_option(ctx)
    for param in command.get_params(ctx):
        if param is help_option:
            continue
        if isinstance(param, click.Argument):
            value = param.make_metavar(ctx)
            parts.append(value)
            continue
        if isinstance(param, click.Option):
            record = param.get_help_record(ctx)
            if record is None:
                continue
            value = record[0].replace(", ", "/").replace(" / ", "/")
            value = _with_default(value, param)
        else:
            continue
        parts.append(value if param.required else f"[{value}]")
    return " ".join(parts)


def _with_default(value: str, option: click.Option) -> str:
    """Append simple non-flag defaults without exposing Click sentinels."""
    default = option.default
    if option.is_flag or isinstance(default, bool):
        return value
    if not isinstance(default, (str, int, float)):
        return value
    return f"{value}={default}"


def _summary(command: click.Command) -> str:
    """Return the first help paragraph on one line."""
    text = command.short_help or command.help or ""
    paragraph = text.strip().split("\n\n", 1)[0]
    return " ".join(paragraph.split()).removesuffix(".")


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
