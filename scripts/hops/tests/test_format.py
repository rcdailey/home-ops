"""Pure unit tests for hops.core.format."""

from __future__ import annotations

import re
from datetime import datetime, timezone


from hops.core.format import age, age_str, format_labels_list, human_bytes, truncate


def test_human_bytes_zero():
    assert human_bytes(0) == "0B"


def test_human_bytes_one_kibibyte():
    assert human_bytes(1024) == "1Ki"


def test_human_bytes_one_mebibyte():
    assert human_bytes(1024 * 1024) == "1Mi"


def test_human_bytes_one_gibibyte():
    assert human_bytes(1024 * 1024 * 1024) == "1Gi"


def test_human_bytes_fractional_kibibyte():
    # 1536 = 1.5 * 1024 -- should show decimal
    result = human_bytes(1536)
    assert "Ki" in result
    assert "1.5" in result


def test_human_bytes_bytes_under_1024():
    assert human_bytes(512) == "512B"


def test_age_seconds():
    assert age(30) == "30s"


def test_age_minutes():
    assert age(120) == "2m"


def test_age_hours():
    assert age(7200) == "2h"


def test_age_days():
    assert age(172800) == "2d"


def test_age_negative_is_future():
    assert age(-1) == "future"


def test_age_zero_seconds():
    assert age(0) == "0s"


def test_age_just_under_minute():
    assert age(59) == "59s"


def test_age_just_under_hour():
    assert age(3599) == "59m"


def test_truncate_short_string_unchanged():
    s = "hello"
    assert truncate(s) == s


def test_truncate_exactly_max_len_unchanged():
    s = "a" * 120
    assert truncate(s) == s


def test_truncate_long_string_truncated():
    s = "a" * 200
    result = truncate(s)
    assert result.endswith("...")
    assert len(result) == 120


def test_truncate_custom_max_len():
    s = "hello world"
    result = truncate(s, max_len=8)
    assert result == "hello..."
    assert len(result) == 8


def test_truncate_empty_string():
    assert truncate("") == ""


def test_age_str_none_returns_question_mark():
    assert age_str(None) == "?"


def test_age_str_empty_string_returns_question_mark():
    assert age_str("") == "?"


def test_age_str_invalid_timestamp_returns_question_mark():
    assert age_str("not-a-timestamp") == "?"


def test_age_str_valid_iso_returns_duration_string():
    # Use a timestamp 2 minutes ago; result should be a duration string
    from datetime import timedelta

    ts = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    result = age_str(ts)
    # Should be a valid duration string like "2m" or close to it
    assert re.match(r"^\d+[smhd]$", result), f"unexpected result: {result!r}"


def test_age_str_z_suffix_timestamp():
    # Kubernetes uses Z suffix; ensure it parses
    from datetime import timedelta

    dt = datetime.now(timezone.utc) - timedelta(hours=1)
    ts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    result = age_str(ts)
    assert re.match(r"^\d+[smhd]$", result), f"unexpected result: {result!r}"


def test_format_labels_list_formats_as_key_value():
    labels = {"app": "plex", "env": "prod"}
    result = format_labels_list(labels)
    assert "app=plex" in result
    assert "env=prod" in result


def test_format_labels_list_filters_excluded_keys():
    labels = {"app": "plex", "helm.sh/chart": "app-template", "env": "prod"}
    result = format_labels_list(labels, exclude={"helm.sh/chart"})
    assert "app=plex" in result
    assert "env=prod" in result
    assert "helm.sh/chart" not in " ".join(result)


def test_format_labels_list_empty_labels():
    assert format_labels_list({}) == []


def test_format_labels_list_exclude_all():
    labels = {"app": "plex"}
    assert format_labels_list(labels, exclude={"app"}) == []
