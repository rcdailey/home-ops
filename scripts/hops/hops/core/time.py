"""Shared time range handling for metrics and log queries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import click

MAX_RANGE_POINTS = 10000


@dataclass
class TimeRange:
    start: str | None = None
    end: str | None = None

    @classmethod
    def from_options(
        cls,
        time_from: str | None,
        time_to: str | None,
        time_at: str | None = None,
        window: str = "10m",
    ) -> TimeRange:
        if time_at:
            half_sec = cls._duration_to_seconds(window) // 2
            at_dt = (
                datetime.now(tz=timezone.utc)
                if time_at == "now"
                else datetime.fromisoformat(time_at)
            )
            if at_dt.tzinfo is None:
                at_dt = at_dt.astimezone()
            at_utc = at_dt.astimezone(timezone.utc)
            start_dt = at_utc - timedelta(seconds=half_sec)
            end_dt = at_utc + timedelta(seconds=half_sec)
            fmt = "%Y-%m-%dT%H:%M:%S"
            return cls(start=start_dt.strftime(fmt), end=end_dt.strftime(fmt))
        return cls(start=time_from, end=time_to)

    def is_current(self) -> bool:
        return self.start is None

    def to_duration(self) -> str:
        if self.start is None:
            raise ValueError("Cannot convert None start to duration")
        if self._is_duration(self.start):
            return self.start
        delta = self._parse_end_time() - self._parse_start_time()
        return f"{int(delta.total_seconds())}s"

    def to_promql_range(self) -> str:
        return f"[{self.to_duration()}]"

    def auto_step(self) -> str:
        """Step sized so a range query stays under the backend point cap.

        VictoriaMetrics rejects range queries yielding more than 30000 points
        per series, so a fixed 1m step silently fails past ~20 days. Target a
        lower ceiling than the hard cap: it keeps long ranges answerable and
        the response small enough to stay useful in a context window.
        """
        if self.start is None:
            return "1m"
        span = int((self._parse_end_time() - self._parse_start_time()).total_seconds())
        return f"{max(60, -(-span // MAX_RANGE_POINTS))}s"

    def to_instant_params(self) -> dict[str, str]:
        """Params pinning an instant query to the end of the range.

        Without this an instant query evaluates its lookbehind window at now,
        so an explicit --to is silently ignored and the caller gets recent data
        labelled as history.
        """
        if not self.end:
            return {}
        return {"time": f"-{self.end}" if self._is_duration(self.end) else self.end}

    def describe(self) -> str:
        """Human label for the window, distinguishing trailing from absolute."""
        if self.end:
            return f"{self.to_duration()} ending {self.end}"
        return f"last {self.to_duration()}"

    def to_range_params(self, step: str = "auto") -> dict[str, str]:
        params: dict[str, str] = {"step": self.auto_step() if step == "auto" else step}
        if self.start:
            params["start"] = (
                f"-{self.start}" if self._is_duration(self.start) else self.start
            )
        if self.end:
            params["end"] = f"-{self.end}" if self._is_duration(self.end) else self.end
        return params

    def _parse_start_time(self) -> datetime:
        if self.start is None:
            return datetime.now(timezone.utc)
        if self._is_duration(self.start):
            return self._parse_end_time() - timedelta(
                seconds=self._duration_to_seconds(self.start)
            )
        return datetime.fromisoformat(self.start.replace("Z", "+00:00"))

    def _parse_end_time(self) -> datetime:
        if self.end is None:
            return datetime.now(timezone.utc)
        if self._is_duration(self.end):
            seconds = self._duration_to_seconds(self.end)
            return datetime.now(timezone.utc).replace(microsecond=0) - timedelta(
                seconds=seconds
            )
        return datetime.fromisoformat(self.end.replace("Z", "+00:00"))

    @staticmethod
    def _is_duration(value: str) -> bool:
        return bool(re.match(r"^\d+[smhdw]$", value))

    @staticmethod
    def _duration_to_seconds(duration: str) -> int:
        unit = duration[-1]
        value = int(duration[:-1])
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
        return value * multipliers.get(unit, 1)


def time_options(default_from=None, support_at=False):
    """Decorator factory for common time range options."""

    def decorator(f):
        f = click.option(
            "--from",
            "time_from",
            default=default_from,
            help="Start time (duration like 24h/7d, or ISO timestamp)",
        )(f)
        f = click.option(
            "--to", "time_to", default=None, help="End time (default: now)"
        )(f)
        if support_at:
            f = click.option(
                "--at",
                "time_at",
                default=None,
                help="Investigate around a specific time (ISO timestamp)",
            )(f)
            f = click.option(
                "--window",
                default="10m",
                help="Window size for --at (default: 10m)",
            )(f)
        return f

    return decorator
