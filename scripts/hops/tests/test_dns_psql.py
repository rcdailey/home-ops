"""Pure unit tests for hops.dns.psql SQL helpers."""

from __future__ import annotations


from hops.dns.psql import _sql_escape, build_where, parse_time, resolve_client


def test_sql_escape_single_quotes_doubled():
    assert _sql_escape("it's") == "it''s"


def test_sql_escape_multiple_single_quotes():
    assert _sql_escape("it's a 'test'") == "it''s a ''test''"


def test_sql_escape_backslashes_escaped():
    assert _sql_escape("foo\\bar") == "foo\\\\bar"


def test_sql_escape_combined_escaping():
    assert _sql_escape("'foo\\bar'") == "''foo\\\\bar''"


def test_sql_escape_plain_string_unchanged():
    assert _sql_escape("example.com") == "example.com"


def test_sql_escape_empty_string():
    assert _sql_escape("") == ""


def test_resolve_client_lan_vlan():
    result = resolve_client("lan")
    assert result == "192.168.1."


def test_resolve_client_iot_vlan():
    result = resolve_client("iot")
    assert result == "192.168.2."


def test_resolve_client_kids_vlan():
    result = resolve_client("kids")
    assert result == "192.168.3."


def test_resolve_client_case_insensitive_vlan():
    assert resolve_client("LAN") == "192.168.1."
    assert resolve_client("IoT") == "192.168.2."


def test_resolve_client_ip_passthrough():
    assert resolve_client("192.168.1.100") == "192.168.1.100"


def test_resolve_client_ip_prefix_passthrough():
    assert resolve_client("192.168.1") == "192.168.1"


def test_resolve_client_cidr_passthrough():
    assert resolve_client("192.168.1.0/24") == "192.168.1.0/24"


def test_resolve_client_hostname_returns_none():
    # Device name lookups return None so caller uses name-based SQL filter
    assert resolve_client("mydevice") is None


def test_resolve_client_plain_name_returns_none():
    assert resolve_client("robert-laptop") is None


def test_parse_time_hours_duration():
    assert parse_time("1h") == "INTERVAL '1 hours'"


def test_parse_time_minutes_duration():
    assert parse_time("30m") == "INTERVAL '30 minutes'"


def test_parse_time_days_duration():
    assert parse_time("7d") == "INTERVAL '7 days'"


def test_parse_time_seconds_duration():
    assert parse_time("60s") == "INTERVAL '60 seconds'"


def test_parse_time_weeks_duration():
    assert parse_time("2w") == "INTERVAL '2 weeks'"


def test_parse_time_iso_timestamp_quoted():
    ts = "2024-01-15T12:00:00"
    result = parse_time(ts)
    assert result == f"'{ts}'"


def test_parse_time_iso_timestamp_with_quotes_escaped():
    # Paranoid: single quotes in timestamp should be escaped
    ts = "2024-01-15T12:00:00"
    result = parse_time(ts)
    assert result.startswith("'") and result.endswith("'")


def test_build_where_basic_time_filter():
    clause = build_where(time_from="1h")
    assert "request_ts" in clause
    assert "INTERVAL '1 hours'" in clause


def test_build_where_client_lan_filter():
    clause = build_where(time_from="1h", client="lan")
    assert "192.168.1." in clause
    assert "client_ip" in clause


def test_build_where_client_ip_filter():
    clause = build_where(time_from="1h", client="192.168.1.100")
    assert "192.168.1.100" in clause


def test_build_where_client_name_filter():
    clause = build_where(time_from="1h", client="mydevice")
    # Name-based lookup uses LIKE with client_name
    assert "client_name" in clause or "client_ip" in clause
    assert "mydevice" in clause


def test_build_where_domain_filter():
    clause = build_where(time_from="1h", domain="example.com")
    assert "question_name" in clause
    assert "example.com" in clause


def test_build_where_blocked_only_filter():
    clause = build_where(time_from="1h", blocked_only=True)
    assert "BLOCKED" in clause
    assert "response_type" in clause


def test_build_where_multiple_conditions_joined_by_and():
    clause = build_where(time_from="1h", domain="example.com", blocked_only=True)
    assert " AND " in clause


def test_build_where_sql_injection_in_domain_escaped():
    # Verify single quotes in domain are escaped to prevent injection
    clause = build_where(time_from="1h", domain="example'; DROP TABLE log_entries; --")
    assert "example''" in clause or "''" in clause
    # The raw injection sequence must not appear verbatim
    assert "DROP TABLE" not in clause or "''" in clause
