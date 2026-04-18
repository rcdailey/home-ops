"""Root CLI group with auto-discovery of subcommand modules."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import click


class _AutoGroup(click.Group):
    """Click group that auto-registers any sibling module exposing ``cli``.

    Modules whose names start with ``_`` are treated as private helpers and
    skipped. The ``cli`` attribute must be a ``click.BaseCommand``.
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
            if info.name.startswith("_") or info.name == "cli":
                continue
            try:
                mod = importlib.import_module(f"hass.{info.name}")
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


@click.group(cls=_AutoGroup, context_settings={"help_option_names": ["-h", "--help"]})
def cli():
    """Home Assistant API wrapper."""
