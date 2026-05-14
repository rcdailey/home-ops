"""Pure unit tests for hops.core.time."""

from __future__ import annotations


from hops.core.time import TimeRange


class TestIsDuration:
    def test_hours(self):
        assert TimeRange._is_duration("1h") is True

    def test_minutes(self):
        assert TimeRange._is_duration("30m") is True

    def test_days(self):
        assert TimeRange._is_duration("7d") is True

    def test_seconds(self):
        assert TimeRange._is_duration("60s") is True

    def test_weeks(self):
        assert TimeRange._is_duration("2w") is True

    def test_iso_date_is_not_duration(self):
        assert TimeRange._is_duration("2024-01-01") is False

    def test_iso_timestamp_is_not_duration(self):
        assert TimeRange._is_duration("2024-01-01T00:00:00") is False

    def test_plain_number_is_not_duration(self):
        assert TimeRange._is_duration("3600") is False

    def test_empty_is_not_duration(self):
        assert TimeRange._is_duration("") is False


class TestDurationToSeconds:
    def test_one_hour(self):
        assert TimeRange._duration_to_seconds("1h") == 3600

    def test_thirty_minutes(self):
        assert TimeRange._duration_to_seconds("30m") == 1800

    def test_seven_days(self):
        assert TimeRange._duration_to_seconds("7d") == 604800

    def test_sixty_seconds(self):
        assert TimeRange._duration_to_seconds("60s") == 60

    def test_two_weeks(self):
        assert TimeRange._duration_to_seconds("2w") == 1209600

    def test_multi_digit(self):
        assert TimeRange._duration_to_seconds("24h") == 86400


class TestFromOptionsPassthrough:
    def test_no_at_returns_passthrough(self):
        tr = TimeRange.from_options(time_from="1h", time_to=None, time_at=None)
        assert tr.start == "1h"
        assert tr.end is None

    def test_with_from_and_to(self):
        tr = TimeRange.from_options(
            time_from="2024-01-01T00:00:00",
            time_to="2024-01-01T01:00:00",
            time_at=None,
        )
        assert tr.start == "2024-01-01T00:00:00"
        assert tr.end == "2024-01-01T01:00:00"

    def test_with_at_computes_window(self):
        # --at now produces a computed start/end pair
        tr = TimeRange.from_options(
            time_from=None, time_to=None, time_at="now", window="10m"
        )
        assert tr.start is not None
        assert tr.end is not None
        # Start should be before end
        assert tr.start < tr.end


class TestIsCurrent:
    def test_no_start_is_current(self):
        tr = TimeRange(start=None, end=None)
        assert tr.is_current() is True

    def test_with_start_is_not_current(self):
        tr = TimeRange(start="1h", end=None)
        assert tr.is_current() is False

    def test_with_both_is_not_current(self):
        tr = TimeRange(start="2024-01-01T00:00:00", end="2024-01-01T01:00:00")
        assert tr.is_current() is False
