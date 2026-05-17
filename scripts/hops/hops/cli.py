"""Root CLI group with auto-discovery of domain modules."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import click

from hops._click import HelpfulGroup


class _AutoGroup(HelpfulGroup):
    """Click group that auto-discovers domain modules in the package.

    Any module in the hops package that exposes a ``cli`` attribute
    (a click.Group or click.Command) is registered as a subcommand.
    Modules whose names start with ``_`` are skipped (private helpers).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._loaded = False

    def _load_plugins(self):
        if self._loaded:
            return
        self._loaded = True
        pkg_path = str(Path(__file__).parent)
        for info in pkgutil.iter_modules([pkg_path]):
            if info.name.startswith("_"):
                continue
            if info.name == "cli":
                continue
            try:
                mod = importlib.import_module(f"hops.{info.name}")
            except Exception:
                continue
            cmd = getattr(mod, "cli", None)
            if isinstance(cmd, click.BaseCommand):
                self.add_command(cmd, info.name)

    def list_commands(self, ctx):
        self._load_plugins()
        return super().list_commands(ctx)

    def get_command(self, ctx, cmd_name):
        self._load_plugins()
        return super().get_command(ctx, cmd_name)


@click.group(
    cls=_AutoGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(version=__import__("hops").__version__, prog_name="hops")
def cli():
    """LLM-optimized cluster operations CLI."""
