"""Output rendering for DNS log queries."""

from __future__ import annotations

import json

import click

from hops.core.format import info, table, truncate
from hops.dns.psql import LOG_FIELDS, TOP_FIELDS, build_where, parse_tsv, psql


def format_log_row(row: dict) -> list[str]:
    """Format a log row for table display."""
    from datetime import datetime

    ts = row.get("request_ts", "")
    try:
        dt = datetime.fromisoformat(ts)
        ts = dt.strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        # Leave the raw timestamp in place when it is not ISO-8601.
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


def query_top_domains(
    time_from: str,
    time_to: str | None,
    client: str | None,
    limit: int,
    json_mode: bool,
    blocked_only: bool = False,
) -> None:
    """Shared implementation for top-domains and top-blocked commands."""
    where = build_where(time_from, time_to, client, blocked_only=blocked_only)
    reason_expr = "STRING_AGG(DISTINCT reason, ', ')" if blocked_only else "''"
    sql = (
        "SELECT question_name, COUNT(*) AS count, "
        "COUNT(DISTINCT client_ip) AS clients, "
        f"{reason_expr} AS reason, "
        "MIN(request_ts) AS first_seen, MAX(request_ts) AS last_seen "
        f"FROM log_entries WHERE {where} "
        f"GROUP BY question_name ORDER BY count DESC LIMIT {limit};"
    )
    output = psql(sql)
    if not output:
        info("No results")
        return

    rows = parse_tsv(output, TOP_FIELDS)
    if json_mode:
        for row in rows:
            click.echo(json.dumps(row))
        return

    headers = ["DOMAIN", "COUNT", "CLIENTS", "FIRST SEEN", "LAST SEEN"]
    if blocked_only:
        headers.insert(3, "REASON")
    table_rows = []
    for r in rows:
        row = [r["question_name"], r["count"], r["clients"]]
        if blocked_only:
            row.append(truncate(r.get("reason", ""), 80))
        row.extend([r["first_seen"], r["last_seen"]])
        table_rows.append(row)
    table(headers, table_rows)
