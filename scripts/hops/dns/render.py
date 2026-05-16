"""Output rendering for DNS log queries."""

from __future__ import annotations

import json

import click

from hops.core.format import info, table, truncate
from hops.dns.psql import LOG_FIELDS, build_where, parse_tsv, psql


def format_log_row(row: dict) -> list[str]:
    """Format a log row for table display."""
    from datetime import datetime

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


def query_dns_logs(
    time_from: str,
    time_to: str | None,
    client: str | None,
    domain: str | None,
    limit: int,
    json_mode: bool,
    blocked_only: bool = False,
) -> None:
    """Shared implementation for logs and blocked commands."""
    where = build_where(time_from, time_to, client, domain, blocked_only=blocked_only)
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

    rows = parse_tsv(output, LOG_FIELDS)
    if json_mode:
        for row in rows:
            click.echo(json.dumps(row))
        return

    table(
        ["TIME", "CLIENT", "QTYPE", "STATUS", "DOMAIN", "REASON", "DUR", "ANSWER"],
        [format_log_row(r) for r in rows],
    )
