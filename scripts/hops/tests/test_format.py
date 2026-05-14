"""Pure unit tests for hops.core.format."""

from __future__ import annotations

import re
from datetime import datetime, timezone


from hops.core.format import age, age_str, format_labels_list, human_bytes, truncate


class TestHumanBytes:
    def test_zero(self):
        assert human_bytes(0) == "0B"

    def test_one_kibibyte(self):
        assert human_bytes(1024) == "1Ki"

    def test_one_mebibyte(self):
        assert human_bytes(1024 * 1024) == "1Mi"

    def test_one_gibibyte(self):
        assert human_bytes(1024 * 1024 * 1024) == "1Gi"

    def test_fractional_kibibyte(self):
        # 1536 = 1.5 * 1024 -- should show decimal
        result = human_bytes(1536)
        assert "Ki" in result
        assert "1.5" in result

    def test_bytes_under_1024(self):
        assert human_bytes(512) == "512B"


class TestAge:
    def test_seconds(self):
        assert age(30) == "30s"

    def test_minutes(self):
        assert age(120) == "2m"

    def test_hours(self):
        assert age(7200) == "2h"

    def test_days(self):
        assert age(172800) == "2d"

    def test_negative_is_future(self):
        assert age(-1) == "future"

    def test_zero_seconds(self):
        assert age(0) == "0s"

    def test_just_under_minute(self):
        assert age(59) == "59s"

    def test_just_under_hour(self):
        assert age(3599) == "59m"


class TestTruncate:
    def test_short_string_unchanged(self):
        s = "hello"
        assert truncate(s) == s

    def test_exactly_max_len_unchanged(self):
        s = "a" * 120
        assert truncate(s) == s

    def test_long_string_truncated(self):
        s = "a" * 200
        result = truncate(s)
        assert result.endswith("...")
        assert len(result) == 120

    def test_custom_max_len(self):
        s = "hello world"
        result = truncate(s, max_len=8)
        assert result == "hello..."
        assert len(result) == 8

    def test_empty_string(self):
        assert truncate("") == ""


class TestAgeStr:
    def test_none_returns_question_mark(self):
        assert age_str(None) == "?"

    def test_empty_string_returns_question_mark(self):
        assert age_str("") == "?"

    def test_invalid_timestamp_returns_question_mark(self):
        assert age_str("not-a-timestamp") == "?"

    def test_valid_iso_returns_duration_string(self):
        # Use a timestamp 2 minutes ago; result should be a duration string
        from datetime import timedelta

        ts = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        result = age_str(ts)
        # Should be a valid duration string like "2m" or close to it
        assert re.match(r"^\d+[smhd]$", result), f"unexpected result: {result!r}"

    def test_z_suffix_timestamp(self):
        # Kubernetes uses Z suffix; ensure it parses
        from datetime import timedelta

        dt = datetime.now(timezone.utc) - timedelta(hours=1)
        ts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = age_str(ts)
        assert re.match(r"^\d+[smhd]$", result), f"unexpected result: {result!r}"


class TestFormatLabelsList:
    def test_formats_as_key_value(self):
        labels = {"app": "plex", "env": "prod"}
        result = format_labels_list(labels)
        assert "app=plex" in result
        assert "env=prod" in result

    def test_filters_excluded_keys(self):
        labels = {"app": "plex", "helm.sh/chart": "app-template", "env": "prod"}
        result = format_labels_list(labels, exclude={"helm.sh/chart"})
        assert "app=plex" in result
        assert "env=prod" in result
        assert "helm.sh/chart" not in " ".join(result)

    def test_empty_labels(self):
        assert format_labels_list({}) == []

    def test_exclude_all(self):
        labels = {"app": "plex"}
        assert format_labels_list(labels, exclude={"app"}) == []
