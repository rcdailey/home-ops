"""PostgreSQL helpers for Blocky DNS log queries.

Queries Blocky DNS logs from PostgreSQL via kubectl exec into CNPG pod.
"""

from __future__ import annotations

import re
import sys

from hops.core.format import info
from hops.core.runner import run

# PostgreSQL connection via kubectl exec
CNPG_NAMESPACE = "dns-private"
CNPG_CLUSTER = "blocky-postgres"
CNPG_DATABASE = "blocky"
CNPG_USER = "postgres"

# Blocky HTTP API
BLOCKY_SERVICE = "blocky"
BLOCKY_HTTP_PORT = 4000
CURL_IMAGE = "curlimages/curl:8.11.1"

# VLAN definitions
VLAN_NAMES = {
    "lan": "192.168.1.",
    "iot": "192.168.2.",
    "kids": "192.168.3.",
    "guest": "192.168.4.",
    "cameras": "192.168.5.",
    "work": "192.168.7.",
}

# Field lists for tab-delimited psql output
LOG_FIELDS = [
    "request_ts",
    "client_ip",
    "client_name",
    "question_name",
    "question_type",
    "reason",
    "response_type",
    "duration_ms",
    "answer",
]

SEARCH_FIELDS = [
    "client_ip",
    "client_name",
    "question_name",
    "response_type",
    "count",
    "first_seen",
    "last_seen",
]


def _sql_escape(value: str) -> str:
    """Escape a string for inclusion in SQL. Prevents injection."""
    return value.replace("'", "''").replace("\\", "\\\\")


def resolve_client(client: str) -> str | None:
    """Resolve VLAN name or pass through IP/prefix.

    Returns None when client value should match by name instead of IP.
    """
    lower = client.lower()
    if lower in VLAN_NAMES:
        return VLAN_NAMES[lower]
    if re.match(r"^\d{1,3}(\.\d{1,3}){0,3}(/\d+)?$", client):
        return client
    return None


def resolve_test_clients(client: str | None) -> list[tuple[str, str]]:
    """Resolve client spec to (display_name, ip) pairs for API testing."""
    if client:
        lower = client.lower()
        if lower in VLAN_NAMES:
            return [(lower, VLAN_NAMES[lower] + "100")]
        return [(client, client)]
    return [(name, prefix + "100") for name, prefix in VLAN_NAMES.items()]


def psql(sql: str) -> str:
    """Execute SQL against the Blocky PostgreSQL database via kubectl exec."""
    pod = f"{CNPG_CLUSTER}-1"
    cmd = [
        "kubectl",
        "exec",
        "-n",
        CNPG_NAMESPACE,
        f"pod/{pod}",
        "-c",
        "postgres",
        "--",
        "psql",
        "-U",
        CNPG_USER,
        "-d",
        CNPG_DATABASE,
        "-t",
        "-A",
        "-F",
        "\t",
        "-c",
        sql,
    ]
    result = run(cmd, timeout=30, check=False)
    if result.returncode != 0:
        msg = (result.stderr or "").strip().split("\n")[0]
        info(f"error: psql failed: {msg}")
        sys.exit(1)
    return result.stdout.strip()


def parse_time(value: str) -> str:
    """Parse a time value to SQL interval or ISO timestamp.

    Accepts: 1h, 24h, 7d, 30m, 60s, 2w, or ISO timestamps.
    """
    match = re.match(r"^(\d+)([smhdw])$", value)
    if match:
        num, unit = int(match.group(1)), match.group(2)
        unit_map = {
            "s": "seconds",
            "m": "minutes",
            "h": "hours",
            "d": "days",
            "w": "weeks",
        }
        return f"INTERVAL '{num} {unit_map[unit]}'"
    # Assume ISO timestamp
    return f"'{_sql_escape(value)}'"


def build_where(
    time_from: str = "1h",
    time_to: str | None = None,
    client: str | None = None,
    domain: str | None = None,
    blocked_only: bool = False,
) -> str:
    """Build WHERE clause for log_entries queries."""
    conditions = []

    # Time range
    interval = parse_time(time_from)
    if interval.startswith("INTERVAL"):
        conditions.append(f"request_ts > NOW() - {interval}")
    else:
        conditions.append(f"request_ts > {interval}")
    if time_to:
        to_interval = parse_time(time_to)
        if to_interval.startswith("INTERVAL"):
            conditions.append(f"request_ts < NOW() - {to_interval}")
        else:
            conditions.append(f"request_ts < {to_interval}")

    # Client filter (escaped to prevent SQL injection)
    if client:
        resolved = resolve_client(client)
        if resolved is None:
            pattern = _sql_escape(client.lower())
            conditions.append(
                f"(LOWER(client_name) LIKE '%{pattern}%'"
                f" OR LOWER(client_ip) LIKE '%{pattern}%')"
            )
        elif "/" in resolved:
            conditions.append(f"client_ip::inet <<= '{_sql_escape(resolved)}'::inet")
        elif resolved.endswith("."):
            conditions.append(f"client_ip LIKE '{_sql_escape(resolved)}%'")
        else:
            conditions.append(f"client_ip LIKE '%{_sql_escape(resolved)}%'")

    # Domain filter (escaped)
    if domain:
        conditions.append(f"question_name LIKE '%{_sql_escape(domain.lower())}%'")

    if blocked_only:
        conditions.append("response_type = 'BLOCKED'")

    return " AND ".join(conditions)


def parse_tsv(output: str, fields: list[str]) -> list[dict]:
    """Parse psql tab-delimited output into dicts."""
    rows = []
    for line in output.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        rows.append(
            {
                field: (parts[i] if i < len(parts) else "")
                for i, field in enumerate(fields)
            }
        )
    return rows
