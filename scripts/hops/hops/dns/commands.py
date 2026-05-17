"""DNS Click commands: logs, blocked, search, test."""

from __future__ import annotations

import json
import os

import click

from hops.core.format import info, table
from hops.core.runner import run
from hops.dns import cli
from hops.dns.psql import (
    BLOCKY_HTTP_PORT,
    BLOCKY_SERVICE,
    CNPG_NAMESPACE,
    CURL_IMAGE,
    SEARCH_FIELDS,
    build_where,
    parse_tsv,
    psql,
    resolve_test_clients,
)
from hops.dns.render import query_dns_logs


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
    query_dns_logs(time_from, time_to, client, domain, limit, json_mode)


@cli.command()
@click.option(
    "-f", "--from", "time_from", default="1h", help="Start time (1h, 24h, 7d, ISO)"
)
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
    query_dns_logs(
        time_from, time_to, client, domain, limit, json_mode, blocked_only=True
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

    rows = parse_tsv(output, SEARCH_FIELDS)
    if json_mode:
        for row in rows:
            click.echo(json.dumps(row))
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
