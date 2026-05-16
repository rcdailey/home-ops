"""Pure unit tests for hops.core.time."""

from __future__ import annotations


from hops.core.time import TimeRange


def test_is_duration_hours():
    assert TimeRange._is_duration("1h") is True


def test_is_duration_minutes():
    assert TimeRange._is_duration("30m") is True


def test_is_duration_days():
    assert TimeRange._is_duration("7d") is True


def test_is_duration_seconds():
    assert TimeRange._is_duration("60s") is True


def test_is_duration_weeks():
    assert TimeRange._is_duration("2w") is True


def test_is_duration_iso_date_is_not_duration():
    assert TimeRange._is_duration("2024-01-01") is False


def test_is_duration_iso_timestamp_is_not_duration():
    assert TimeRange._is_duration("2024-01-01T00:00:00") is False


def test_is_duration_plain_number_is_not_duration():
    assert TimeRange._is_duration("3600") is False


def test_is_duration_empty_is_not_duration():
    assert TimeRange._is_duration("") is False


def test_duration_to_seconds_one_hour():
    assert TimeRange._duration_to_seconds("1h") == 3600


def test_duration_to_seconds_thirty_minutes():
    assert TimeRange._duration_to_seconds("30m") == 1800


def test_duration_to_seconds_seven_days():
    assert TimeRange._duration_to_seconds("7d") == 604800


def test_duration_to_seconds_sixty_seconds():
    assert TimeRange._duration_to_seconds("60s") == 60


def test_duration_to_seconds_two_weeks():
    assert TimeRange._duration_to_seconds("2w") == 1209600


def test_duration_to_seconds_multi_digit():
    assert TimeRange._duration_to_seconds("24h") == 86400


def test_from_options_no_at_returns_passthrough():
    tr = TimeRange.from_options(time_from="1h", time_to=None, time_at=None)
    assert tr.start == "1h"
    assert tr.end is None


def test_from_options_with_from_and_to():
    tr = TimeRange.from_options(
        time_from="2024-01-01T00:00:00",
        time_to="2024-01-01T01:00:00",
        time_at=None,
    )
    assert tr.start == "2024-01-01T00:00:00"
    assert tr.end == "2024-01-01T01:00:00"


def test_from_options_with_at_computes_window():
    # --at now produces a computed start/end pair
    tr = TimeRange.from_options(
        time_from=None, time_to=None, time_at="now", window="10m"
    )
    assert tr.start is not None
    assert tr.end is not None
    # Start should be before end
    assert tr.start < tr.end


def test_is_current_no_start_is_current():
    tr = TimeRange(start=None, end=None)
    assert tr.is_current() is True


def test_is_current_with_start_is_not_current():
    tr = TimeRange(start="1h", end=None)
    assert tr.is_current() is False


def test_is_current_with_both_is_not_current():
    tr = TimeRange(start="2024-01-01T00:00:00", end="2024-01-01T01:00:00")
    assert tr.is_current() is False
