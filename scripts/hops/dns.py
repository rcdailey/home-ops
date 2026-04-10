"""DNS domain: Blocky DNS query log analysis (port of blocky.py).

Queries Blocky DNS logs from PostgreSQL via kubectl exec into CNPG pod.
All functionality preserved from the original script.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime

import click

from hops._format import info, table, truncate
from hops._runner import run

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
    return f"'{value}'"


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

    # Client filter
    if client:
        resolved = resolve_client(client)
        if resolved is None:
            # Name pattern
            pattern = client.lower()
            conditions.append(
                f"(LOWER(client_name) LIKE '%{pattern}%' OR LOWER(client_ip) LIKE '%{pattern}%')"
            )
        elif "/" in resolved:
            # CIDR
            conditions.append(f"client_ip::inet <<= '{resolved}'::inet")
        elif resolved.endswith("."):
            # VLAN prefix
            conditions.append(f"client_ip LIKE '{resolved}%'")
        else:
            # Partial or full IP
            conditions.append(f"client_ip LIKE '%{resolved}%'")

    # Domain filter
    if domain:
        conditions.append(f"question_name LIKE '%{domain.lower()}%'")

    # Blocked only
    if blocked_only:
        conditions.append("response_type = 'BLOCKED'")

    return " AND ".join(conditions)


def format_log_row(row: dict) -> list[str]:
    """Format a log row for table display."""
    ts = row.get("request_ts", "")
    try:
        dt = datetime.fromisoformat(ts)
        ts = dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    client = row.get("client_ip", "")
    name = row.get("client_name", "")
    if name and name != client:
        client = f"{client} ({name})"
    qname = row.get("question_name", "")
    qtype = row.get("question_type", "")
    rtype = row.get("response_type", "")
    reason = row.get("reason", "")
    duration = row.get("duration_ms", "")
    duration_str = f"{duration}ms" if duration else ""
    answer = truncate(row.get("answer", ""), 50)
    return [ts, client, qtype, rtype, qname, reason, duration_str, answer]


def parse_log_rows(output: str) -> list[dict]:
    """Parse psql tab-delimited output into dicts."""
    fields = [
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
    rows = []
    for line in output.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        row = {}
        for i, field in enumerate(fields):
            row[field] = parts[i] if i < len(parts) else ""
        rows.append(row)
    return rows


def parse_search_rows(output: str) -> list[dict]:
    """Parse psql tab-delimited search output into dicts."""
    fields = [
        "client_ip",
        "client_name",
        "question_name",
        "response_type",
        "count",
        "first_seen",
        "last_seen",
    ]
    rows = []
    for line in output.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        row = {}
        for i, field in enumerate(fields):
            row[field] = parts[i] if i < len(parts) else ""
        rows.append(row)
    return rows


@click.group()
def cli():
    """Blocky DNS query log analysis."""


@cli.command()
@click.option(
    "-f", "--from", "time_from", default="1h", help="Start time (1h, 24h, 7d, ISO)"
)
@click.option("-t", "--to", "time_to", default=None, help="End time")
@click.option("-c", "--client", help="Client IP, device name, CIDR, or VLAN name")
@click.option("-d", "--domain", help="Domain substring filter")
@click.option("-l", "--limit", default=100, help="Max rows (default: 100)")
@click.option("--json", "json_mode", is_flag=True, help="Output NDJSON")
def logs(
    time_from: str,
    time_to: str | None,
    client: str | None,
    domain: str | None,
    limit: int,
    json_mode: bool,
):
    """Show recent DNS query log entries."""
    where = build_where(time_from, time_to, client, domain)
    sql = (
        "SELECT request_ts, client_ip, client_name, question_name, question_type, "
        "reason, response_type, duration_ms, answer "
        f"FROM log_entries WHERE {where} "
        f"ORDER BY request_ts DESC LIMIT {limit};"
    )
    output = psql(sql)
    if not output:
        info("No results")
        return

    rows = parse_log_rows(output)
    if json_mode:
        for row in rows:
            print(json.dumps(row))
        return

    table(
        ["TIME", "CLIENT", "QTYPE", "STATUS", "DOMAIN", "REASON", "DUR", "ANSWER"],
        [format_log_row(r) for r in rows],
    )


@cli.command()
@click.option("-f", "--from", "time_from", default="1h", help="Start time")
@click.option("-t", "--to", "time_to", default=None, help="End time")
@click.option("-c", "--client", help="Client IP, device name, CIDR, or VLAN")
@click.option("-d", "--domain", help="Domain substring filter")
@click.option("-l", "--limit", default=100, help="Max rows")
@click.option("--json", "json_mode", is_flag=True, help="Output NDJSON")
def blocked(
    time_from: str,
    time_to: str | None,
    client: str | None,
    domain: str | None,
    limit: int,
    json_mode: bool,
):
    """Show blocked DNS queries only."""
    where = build_where(time_from, time_to, client, domain, blocked_only=True)
    sql = (
        "SELECT request_ts, client_ip, client_name, question_name, question_type, "
        "reason, response_type, duration_ms, answer "
        f"FROM log_entries WHERE {where} "
        f"ORDER BY request_ts DESC LIMIT {limit};"
    )
    output = psql(sql)
    if not output:
        info("No results")
        return

    rows = parse_log_rows(output)
    if json_mode:
        for row in rows:
            print(json.dumps(row))
        return

    table(
        ["TIME", "CLIENT", "QTYPE", "STATUS", "DOMAIN", "REASON", "DUR", "ANSWER"],
        [format_log_row(r) for r in rows],
    )


@cli.command()
@click.argument("pattern")
@click.option(
    "-f", "--from", "time_from", default="24h", help="Start time (default: 24h)"
)
@click.option("-t", "--to", "time_to", default=None, help="End time")
@click.option("-l", "--limit", default=50, help="Max rows (default: 50)")
@click.option("--json", "json_mode", is_flag=True, help="Output NDJSON")
def search(
    pattern: str, time_from: str, time_to: str | None, limit: int, json_mode: bool
):
    """Search for a domain across all clients."""
    where = build_where(time_from, time_to, domain=pattern)
    sql = (
        "SELECT client_ip, client_name, question_name, response_type, "
        "COUNT(*) AS count, MIN(request_ts) AS first_seen, MAX(request_ts) AS last_seen "
        f"FROM log_entries WHERE {where} "
        "GROUP BY client_ip, client_name, question_name, response_type "
        f"ORDER BY last_seen DESC LIMIT {limit};"
    )
    output = psql(sql)
    if not output:
        info("No results")
        return

    rows = parse_search_rows(output)
    if json_mode:
        for row in rows:
            print(json.dumps(row))
        return

    table_rows = []
    for r in rows:
        client = r["client_ip"]
        name = r.get("client_name", "")
        if name and name != client:
            client = f"{client} ({name})"
        table_rows.append(
            [
                client,
                r["question_name"],
                r["response_type"],
                r["count"],
                r["first_seen"],
                r["last_seen"],
            ]
        )
    table(
        ["CLIENT", "DOMAIN", "STATUS", "COUNT", "FIRST SEEN", "LAST SEEN"],
        table_rows,
    )


@cli.command("test")
@click.argument("domains", nargs=-1, required=True)
@click.option("-c", "--client", help="Client IP or VLAN name (default: all VLANs)")
@click.option("--type", "qtype", default="A", help="DNS record type (default: A)")
def test_blocking(domains: tuple[str, ...], client: str | None, qtype: str):
    """Test DNS blocking for domains against client groups via Blocky API."""
    clients = resolve_test_clients(client)

    # Build curl commands for each domain/client combination
    url = f"http://{BLOCKY_SERVICE}.{CNPG_NAMESPACE}:{BLOCKY_HTTP_PORT}/api/query"
    script_parts = []
    for i, (cname, cip) in enumerate(clients):
        for j, domain in enumerate(domains):
            idx = i * len(domains) + j
            script_parts.append(
                f'echo -n "{idx}:"; '
                f'curl -sS -X POST -H "Content-Type: application/json" '
                f'-H "X-Forwarded-For: {cip}" '
                f'-d \'{{"query":"{domain}","type":"{qtype}"}}\' '
                f'"{url}" 2>/dev/null || echo \'{{"error":true}}\''
            )

    script = "; echo; ".join(script_parts)
    pod_name = f"blocky-test-{os.getpid()}"
    cmd = [
        "kubectl",
        "run",
        pod_name,
        "--rm",
        "-i",
        "--restart=Never",
        f"--image={CURL_IMAGE}",
        "--",
        "sh",
        "-c",
        script,
    ]

    result = run(cmd, timeout=60, check=False)
    if result.returncode != 0 and not result.stdout:
        info(f"error: test pod failed: {(result.stderr or '').strip()}")
        return

    # Parse responses
    responses: dict[int, dict | None] = {}
    for line in (result.stdout or "").strip().split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        idx_str, rest = line.split(":", 1)
        try:
            idx = int(idx_str)
            data = json.loads(rest)
            responses[idx] = None if data.get("error") else data
        except (ValueError, json.JSONDecodeError):
            pass

    # Build result table
    rows = []
    for i, (cname, cip) in enumerate(clients):
        for j, domain in enumerate(domains):
            idx = i * len(domains) + j
            resp = responses.get(idx)
            if resp is None:
                status = "ERROR"
                response_str = ""
                reason = ""
            else:
                resp_type = resp.get("response", "")
                reason = resp.get("reason", "")
                status = resp.get("returnCode", resp_type)
                response_str = resp_type
            rows.append([domain, cname, cip, status, response_str, reason])

    table(
        ["DOMAIN", "CLIENT", "IP", "STATUS", "RESPONSE", "REASON"],
        rows,
    )
