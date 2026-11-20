"""Custom Click classes that show full help on usage errors."""

from __future__ import annotations

import click


class HelpfulGroup(click.Group):
    """Click group that appends the failing command's help to usage errors."""

    def invoke(self, ctx: click.Context) -> None:
        try:
            return super().invoke(ctx)
        except click.UsageError as exc:
            click.echo(exc.format_message(), err=True)
            if exc.ctx is not None:
                click.echo("", err=True)
                click.echo(exc.ctx.get_help(), err=True)
            raise SystemExit(exc.exit_code) from None
