"""Decode and encode OpenSprinkler program records (/jp pd entries, /cp writes)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from opensprinkler._client import ApiError, call

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_TYPES = {0: "weekly", 1: "single-run", 2: "monthly", 3: "interval"}


@dataclass
class Program:
    """One program as stored on the controller.

    `flag` bits: 0 enabled, 1 use weather, 2-3 odd/even, 4-5 day type, 6 fixed start
    times, 7 date range. The enable bit belongs to whoever toggles programs (Home
    Assistant here); edits preserve it.
    """

    pid: int
    flag: int
    days0: int
    days1: int
    starts: list[int]
    durations: list[int]
    name: str
    date_range: list[int] = field(default_factory=lambda: [0, 33, 415])

    @classmethod
    def from_pd(cls, pid: int, pd: list[Any]) -> Program:
        return cls(
            pid, pd[0], pd[1], pd[2], list(pd[3]), list(pd[4]), pd[5], list(pd[6])
        )

    def bit(self, n: int) -> bool:
        return bool(self.flag >> n & 1)

    def set_bit(self, n: int, on: bool) -> None:
        self.flag = self.flag | 1 << n if on else self.flag & ~(1 << n)

    @property
    def day_type(self) -> int:
        return self.flag >> 4 & 3

    def set_weekly(self, days: list[str]) -> None:
        self.flag &= ~(3 << 4)
        self.days0 = sum(1 << WEEKDAYS.index(d) for d in days)
        self.days1 = 0

    def set_interval(self, every: int, offset: int) -> None:
        self.flag |= 3 << 4
        self.days0, self.days1 = offset, every

    def write(self) -> None:
        """Replace the whole program on the controller (pid -1 appends a new one).

        Flag bit 7 enables the date range; `from`/`to` carry its bounds.
        """
        v = f"[{self.flag},{self.days0},{self.days1},{list_str(self.starts)},"
        v += f"{list_str(self.durations)}]"
        call(
            "cp",
            {
                "pid": self.pid,
                "v": v,
                "name": self.name,
                "from": self.date_range[1],
                "to": self.date_range[2],
            },
        )


def list_str(values: list[int]) -> str:
    return "[" + ",".join(map(str, values)) + "]"


def load_programs() -> list[Program]:
    return [Program.from_pd(i, pd) for i, pd in enumerate(call("jp")["pd"])]


def find_program(ref: str, programs: list[Program]) -> Program:
    """Resolve a program by 0-based index or exact (case-insensitive) name."""
    if ref.isdigit() and int(ref) < len(programs):
        return programs[int(ref)]
    for p in programs:
        if p.name.lower() == ref.lower():
            return p
    raise ApiError(f"no program named {ref!r}; see `program list`")


def parse_month_day(value: str) -> int:
    """MM-DD to the firmware's (month << 5) + day encoding."""
    month, day = (int(x) for x in value.split("-"))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        raise ApiError(f"bad date {value!r}; use MM-DD")
    return (month << 5) + day


def format_month_day(value: int) -> str:
    return f"{value >> 5:02d}-{value & 31:02d}"


def format_time(value: int) -> str:
    """Decode one start-time value: minutes after midnight, or a sunrise/sunset offset."""
    if value & 1 << 15:
        return "off"
    if value & 3 << 13:
        anchor = "sunset" if value & 1 << 13 else "sunrise"
        offset = value & 0x7FF
        sign = "-" if value & 1 << 12 else "+"
        return f"{anchor}{sign}{offset}m" if offset else anchor
    return f"{value // 60}:{value % 60:02d}"


def parse_time(value: str) -> int:
    hours, minutes = (int(x) for x in value.split(":"))
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        raise ApiError(f"bad time {value!r}; use HH:MM")
    return hours * 60 + minutes


def describe(p: Program, names: list[str]) -> str:
    """Multi-line prose summary of a program."""
    if p.day_type == 0:
        days = (
            ",".join(d for i, d in enumerate(WEEKDAYS) if p.days0 >> i & 1) or "no days"
        )
    elif p.day_type == 3:
        days = f"every {p.days1} days (offset {p.days0})"
    else:
        days = f"{DAY_TYPES[p.day_type]} ({p.days0},{p.days1})"
    if p.bit(6):
        starts = ", ".join(format_time(s) for s in p.starts if format_time(s) != "off")
    else:
        first, count, interval = p.starts[:3]
        starts = format_time(first)
        if count:
            starts += f", then {count} more every {interval} min"
    window = "all year"
    if p.bit(7):
        window = f"{format_month_day(p.date_range[1])} to {format_month_day(p.date_range[2])}"
    zones = ", ".join(
        f"{names[i]} {d / 60:g}m"
        for i, d in enumerate(p.durations)
        if d and i < len(names)
    )
    return (
        f"#{p.pid} {p.name}: {'enabled' if p.bit(0) else 'disabled'}, "
        f"weather {'on' if p.bit(1) else 'off'}\n"
        f"  days {days}; starts {starts}; active {window}\n"
        f"  zones: {zones or 'none'}"
    )
