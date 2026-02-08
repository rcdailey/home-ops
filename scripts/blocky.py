#!/usr/bin/env python3

"""Query Blocky DNS query logs from PostgreSQL.

Examples:
  # Recent DNS queries (default last 1h)
  %(prog)s logs

  # Queries from a specific client (by IP, device name, or VLAN)
  %(prog)s logs -c 192.168.3.40
  %(prog)s logs -c pixel -f 1h

  # Queries for a domain from a client in the last 24h
  %(prog)s logs -c 192.168.3.40 -d homedepot.com -f 24h

  # All blocked queries for a client
  %(prog)s blocked -c 192.168.3.40 -f 24h

  # Search for a domain across all clients
  %(prog)s search homedepot -f 24h

  # Machine-readable output
  %(prog)s -j blocked -c 192.168.3.40

  # Test if a domain is blocked for kids VLAN
  %(prog)s test pornhub.com -c kids

  # Test multiple domains against all VLANs
  %(prog)s test pornhub.com tiktok.com draftkings.com
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

CNPG_NAMESPACE = "dns-private"
CNPG_CLUSTER = "blocky-postgres"
CNPG_DATABASE = "blocky"
CNPG_USER = "postgres"

BLOCKY_SERVICE = "blocky"
BLOCKY_HTTP_PORT = 4000
CURL_IMAGE = "curlimages/curl:8.11.1"

VLAN_NAMES = {
    "lan": "192.168.1.",
    "iot": "192.168.2.",
    "kids": "192.168.3.",
    "guest": "192.168.4.",
    "cameras": "192.168.5.",
    "work": "192.168.7.",
}

COLORS = {
    "red": "\033[0;31m",
    "yellow": "\033[1;33m",
    "green": "\033[0;32m",
    "blue": "\033[0;34m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}

REASON_COLORS = {
    "BLOCKED": "red",
    "CACHED": "green",
    "RESOLVED": "blue",
    "CONDITIONAL": "yellow",
    "CUSTOMDNS": "yellow",
    "NOTFQDN": "dim",
}

_json_mode = False


def colorize(text: str, color: str) -> str:
    if _json_mode:
        return text
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


@dataclass
class TimeRange:
    start: str | None = None
    end: str | None = None

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "TimeRange":
        return cls(
            start=getattr(args, "time_from", None),
            end=getattr(args, "time_to", None),
        )

    def to_sql_interval(self) -> str:
        """Convert duration string to PostgreSQL interval."""
        if self.start is None:
            return "1 hour"
        if self._is_duration(self.start):
            unit = self.start[-1]
            value = int(self.start[:-1])
            units = {
                "s": "seconds",
                "m": "minutes",
                "h": "hours",
                "d": "days",
                "w": "weeks",
            }
            return f"{value} {units.get(unit, 'hours')}"
        # ISO timestamp: return as-is for direct comparison
        return self.start

    def to_sql_condition(self) -> str:
        """Build SQL WHERE clause for time range."""
        parts = []
        if self.start:
            if self._is_duration(self.start):
                interval = self.to_sql_interval()
                parts.append(f"request_ts > NOW() - INTERVAL '{interval}'")
            else:
                parts.append(f"request_ts > '{self.start}'")
        else:
            parts.append("request_ts > NOW() - INTERVAL '1 hour'")

        if self.end:
            if self._is_duration(self.end):
                unit = self.end[-1]
                value = int(self.end[:-1])
                units = {
                    "s": "seconds",
                    "m": "minutes",
                    "h": "hours",
                    "d": "days",
                    "w": "weeks",
                }
                interval = f"{value} {units.get(unit, 'hours')}"
                parts.append(f"request_ts < NOW() - INTERVAL '{interval}'")
            else:
                parts.append(f"request_ts < '{self.end}'")

        return " AND ".join(parts)

    @staticmethod
    def _is_duration(value: str) -> bool:
        return bool(re.match(r"^\d+[smhdw]$", value))


def add_time_args(
    parser: argparse.ArgumentParser,
    default_start: str = "1h",
) -> None:
    parser.add_argument(
        "-f",
        "--from",
        dest="time_from",
        default=default_start,
        metavar="TIME",
        help="Start time (duration like 1h/24h/7d, or ISO timestamp; default: %(default)s)",
    )
    parser.add_argument(
        "-t",
        "--to",
        dest="time_to",
        metavar="TIME",
        help="End time (default: now)",
    )


def resolve_client(client: str) -> str | None:
    """Resolve VLAN name or pass through IP/prefix.

    Returns None when the client value should match by name instead of IP.
    """
    lower = client.lower()
    if lower in VLAN_NAMES:
        return VLAN_NAMES[lower]
    # Looks like an IP or CIDR
    if re.match(r"^\d{1,3}(\.\d{1,3}){0,3}(/\d+)?$", client):
        return client
    # Not an IP; treat as a name pattern
    return None


def resolve_test_clients(client: str | None) -> list[tuple[str, str]]:
    """Resolve client spec to (display_name, ip) pairs for API testing."""
    if client:
        if client in VLAN_NAMES:
            return [(client, VLAN_NAMES[client] + "100")]
        return [(client, client)]
    return [(name, prefix + "100") for name, prefix in VLAN_NAMES.items()]


def run_psql(sql: str) -> str:
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
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print("Error: psql query timed out after 30s", file=sys.stderr)
        sys.exit(1)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        print(f"Error: psql failed: {stderr}", file=sys.stderr)
        sys.exit(1)

    return result.stdout.strip()


def run_blocky_api(
    queries: list[tuple[str, str, str]],
) -> list[dict[str, str] | None]:
    """Query Blocky's HTTP API with client IP spoofing via X-Forwarded-For.

    Each query is a (domain, qtype, client_ip) tuple. All queries run in a
    single ephemeral pod for efficiency.
    """
    url = f"http://{BLOCKY_SERVICE}.{CNPG_NAMESPACE}:{BLOCKY_HTTP_PORT}/api/query"

    curl_cmds = []
    for i, (domain, qtype, client_ip) in enumerate(queries):
        payload = json.dumps({"query": domain, "type": qtype})
        # Prefix each response with index for reliable matching
        curl_cmds.append(
            f"(printf '{i}:' && curl -sf"
            f" -H 'Content-Type: application/json'"
            f" -H 'X-Forwarded-For: {client_ip}'"
            f" -d '{payload}'"
            f" '{url}' && echo"
            f" || echo '{{\"error\":true}}')"
        )

    script = "; ".join(curl_cmds)
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

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        print("Error: API query timed out", file=sys.stderr)
        sys.exit(1)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        # Filter kubectl pod lifecycle noise
        lines = [
            line
            for line in stderr.splitlines()
            if not line.startswith("pod ") and "already exists" not in line
        ]
        if lines:
            print(f"Error: API query failed: {lines[0]}", file=sys.stderr)
            sys.exit(1)

    results: list[dict[str, str] | None] = [None] * len(queries)
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        idx_str, _, payload = line.partition(":")
        try:
            idx = int(idx_str)
        except ValueError:
            continue
        if idx < 0 or idx >= len(queries):
            continue
        try:
            data = json.loads(payload)
            results[idx] = None if data.get("error") else data
        except json.JSONDecodeError:
            pass

    return results


def parse_rows(output: str, columns: list[str]) -> list[dict[str, str]]:
    """Parse tab-separated psql output into list of dicts."""
    rows = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        values = line.split("\t")
        if len(values) != len(columns):
            continue
        rows.append(dict(zip(columns, values)))
    return rows


def build_where(
    time_range: TimeRange,
    client: str | None = None,
    domain: str | None = None,
    blocked_only: bool = False,
) -> str:
    """Build WHERE clause from common filters."""
    conditions = [time_range.to_sql_condition()]

    if client:
        resolved = resolve_client(client)
        if resolved is None:
            # Name pattern: match against client_name or client_ip, case-insensitive
            pattern = client.lower()
            conditions.append(
                f"(LOWER(client_name) LIKE '%{pattern}%'"
                f" OR LOWER(client_ip) LIKE '%{pattern}%')"
            )
        elif resolved.endswith("."):
            # VLAN prefix match
            conditions.append(f"client_ip LIKE '{resolved}%'")
        elif "/" in resolved:
            # CIDR notation
            conditions.append(f"client_ip::inet <<= '{resolved}'::inet")
        else:
            # Partial or full IP match
            conditions.append(f"client_ip LIKE '%{resolved}%'")

    if domain:
        conditions.append(f"question_name LIKE '%{domain}%'")

    if blocked_only:
        conditions.append("response_type = 'BLOCKED'")

    return " AND ".join(conditions)


def format_log_row(row: dict[str, str]) -> str:
    """Format a single log entry for terminal display."""
    ts = row.get("request_ts", "")[:19]
    client = row.get("client_ip", "")
    name = row.get("client_name", "")
    domain = row.get("question_name", "")
    qtype = row.get("question_type", "")
    reason = row.get("reason", "")
    rtype = row.get("response_type", "")
    duration = row.get("duration_ms", "")
    answer = row.get("answer", "")

    color = REASON_COLORS.get(rtype, "dim")
    status = colorize(rtype, color)

    client_display = f"{client} ({name})" if name else client

    parts = [
        colorize(ts, "dim"),
        f"{client_display:>20s}",
        f"{qtype:>5s}",
        status,
        domain,
    ]

    if reason and reason != rtype:
        parts.append(colorize(f"[{reason}]", "dim"))
    if duration:
        parts.append(colorize(f"{duration}ms", "dim"))
    if answer:
        parts.append(colorize(f"-> {answer}", "dim"))

    return "  ".join(parts)


def print_table(
    headers: list[str],
    rows: list[list[str]],
    alignments: list[str],
    colors: list | None = None,
) -> None:
    """Print a dynamically-sized table that fits the terminal."""
    term_width = shutil.get_terminal_size().columns
    gap = "  "

    # Compute column widths from headers and data
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(val))

    total = sum(widths) + len(gap) * (len(widths) - 1)

    # Header
    parts = []
    for header, width, align in zip(headers, widths, alignments):
        parts.append(f"{header:{align}{width}s}")
    print(gap.join(parts))
    print("-" * min(total, term_width))

    # Data rows
    for row in rows:
        parts = []
        for i, (val, width, align) in enumerate(zip(row, widths, alignments)):
            if colors and colors[i]:
                colored_val = colors[i](val)
                pad = max(0, width - len(val))
                if align == ">":
                    parts.append(" " * pad + colored_val)
                else:
                    parts.append(colored_val + " " * pad)
            else:
                parts.append(f"{val:{align}{width}s}")
        print(gap.join(parts))


def cmd_logs(args: argparse.Namespace) -> int:
    """Show recent DNS query log entries."""
    time_range = TimeRange.from_args(args)
    where = build_where(
        time_range,
        client=args.client,
        domain=args.domain,
    )

    sql = f"""\
SELECT request_ts, client_ip, client_name, question_name, question_type,
       reason, response_type, duration_ms, answer
FROM log_entries
WHERE {where}
ORDER BY request_ts DESC
LIMIT {args.limit};"""

    output = run_psql(sql)
    if not output:
        print("No results.", file=sys.stderr)
        return 0

    columns = [
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
    rows = parse_rows(output, columns)

    if _json_mode:
        for row in rows:
            print(json.dumps(row))
        return 0

    # Display oldest first for chronological reading
    for row in reversed(rows):
        print(format_log_row(row))

    print(f"\nTotal: {len(rows)} entries", file=sys.stderr)
    return 0


def cmd_blocked(args: argparse.Namespace) -> int:
    """Show blocked DNS queries."""
    time_range = TimeRange.from_args(args)
    where = build_where(
        time_range,
        client=args.client,
        domain=args.domain,
        blocked_only=True,
    )

    sql = f"""\
SELECT request_ts, client_ip, client_name, question_name, question_type,
       reason, response_type, duration_ms, answer
FROM log_entries
WHERE {where}
ORDER BY request_ts DESC
LIMIT {args.limit};"""

    output = run_psql(sql)
    if not output:
        print("No blocked queries found.", file=sys.stderr)
        return 0

    columns = [
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
    rows = parse_rows(output, columns)

    if _json_mode:
        for row in rows:
            print(json.dumps(row))
        return 0

    for row in reversed(rows):
        print(format_log_row(row))

    print(f"\nTotal: {len(rows)} blocked entries", file=sys.stderr)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Search for a domain across all clients."""
    time_range = TimeRange.from_args(args)
    where = build_where(time_range, domain=args.pattern)

    sql = f"""\
SELECT client_ip, client_name, response_type,
       COUNT(*) AS count,
       MIN(request_ts) AS first_seen,
       MAX(request_ts) AS last_seen
FROM log_entries
WHERE {where}
GROUP BY client_ip, client_name, response_type
ORDER BY last_seen DESC
LIMIT {args.limit};"""

    output = run_psql(sql)
    if not output:
        print(f"No queries matching '{args.pattern}' found.", file=sys.stderr)
        return 0

    columns = [
        "client_ip",
        "client_name",
        "response_type",
        "count",
        "first_seen",
        "last_seen",
    ]
    rows = parse_rows(output, columns)

    if _json_mode:
        for row in rows:
            print(json.dumps(row))
        return 0

    # Drop Name column when it always matches Client IP (no useful info)
    show_name = any(r["client_name"] != r["client_ip"] for r in rows)

    headers = ["Client"]
    alignments = ["<"]
    color_fns: list = [None]

    if show_name:
        headers.append("Name")
        alignments.append("<")
        color_fns.append(None)

    headers.extend(["Status", "Count", "First Seen", "Last Seen"])
    alignments.extend(["<", ">", "<", "<"])
    color_fns.extend(
        [
            lambda v: colorize(v, REASON_COLORS.get(v, "dim")),
            None,
            lambda v: colorize(v, "dim"),
            lambda v: colorize(v, "dim"),
        ]
    )

    table_rows = []
    for row in rows:
        r = [row["client_ip"]]
        if show_name:
            r.append(row["client_name"])
        r.extend(
            [
                row["response_type"],
                row["count"],
                row["first_seen"][:19],
                row["last_seen"][:19],
            ]
        )
        table_rows.append(r)

    print_table(headers, table_rows, alignments, color_fns)

    print(f"\nTotal: {len(rows)} client/status combinations", file=sys.stderr)
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    """Test DNS blocking for domains against client groups via Blocky API."""
    domains = args.domains
    qtype = args.type
    clients = resolve_test_clients(args.client)

    # Build query list and track metadata for display
    queries: list[tuple[str, str, str]] = []
    meta: list[tuple[str, str, str]] = []
    for domain in domains:
        for client_name, client_ip in clients:
            queries.append((domain, qtype, client_ip))
            meta.append((domain, client_name, client_ip))

    results = run_blocky_api(queries)

    if _json_mode:
        for i, result in enumerate(results):
            domain, client_name, client_ip = meta[i]
            entry: dict[str, str] = {
                "domain": domain,
                "client": client_name,
                "clientIP": client_ip,
            }
            if result:
                entry.update(result)
            else:
                entry["error"] = "true"
            print(json.dumps(entry))
        return 0

    # Build table
    headers = ["Domain", "Client", "Client IP", "Status", "Response", "Reason"]
    alignments = ["<", "<", "<", "<", "<", "<"]
    color_fns: list = [
        None,
        None,
        lambda v: colorize(v, "dim"),
        lambda v: colorize(v, REASON_COLORS.get(v, "dim")),
        lambda v: colorize(v, "dim"),
        lambda v: colorize(v, "dim"),
    ]

    table_rows = []
    for i, result in enumerate(results):
        domain, client_name, client_ip = meta[i]
        if result:
            status = result.get("responseType", "UNKNOWN")
            response = result.get("response", "")
            reason = result.get("reason", "")
        else:
            status = "ERROR"
            response = ""
            reason = "query failed"
        table_rows.append([domain, client_name, client_ip, status, response, reason])

    print_table(headers, table_rows, alignments, color_fns)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query Blocky DNS logs from PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Output as newline-delimited JSON",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # logs
    p_logs = subparsers.add_parser(
        "logs",
        help="Show recent DNS query log entries",
    )
    add_time_args(p_logs)
    p_logs.add_argument(
        "-c",
        "--client",
        help="Client IP (partial), device name (partial), CIDR, or VLAN name",
    )
    p_logs.add_argument("-d", "--domain", help="Domain substring filter")
    p_logs.add_argument(
        "-l", "--limit", type=int, default=100, help="Max rows (default: 100)"
    )

    # blocked
    p_blocked = subparsers.add_parser(
        "blocked",
        help="Show blocked DNS queries",
    )
    add_time_args(p_blocked)
    p_blocked.add_argument(
        "-c",
        "--client",
        help="Client IP (partial), device name (partial), CIDR, or VLAN name",
    )
    p_blocked.add_argument("-d", "--domain", help="Domain substring filter")
    p_blocked.add_argument(
        "-l", "--limit", type=int, default=100, help="Max rows (default: 100)"
    )

    # search
    p_search = subparsers.add_parser(
        "search",
        help="Search for a domain across all clients",
    )
    p_search.add_argument("pattern", help="Domain substring to search for")
    add_time_args(p_search, default_start="24h")
    p_search.add_argument(
        "-l", "--limit", type=int, default=50, help="Max rows (default: 50)"
    )

    # test
    p_test = subparsers.add_parser(
        "test",
        help="Test DNS blocking for domains against client groups",
    )
    p_test.add_argument(
        "domains",
        nargs="+",
        help="Domain(s) to test",
    )
    p_test.add_argument(
        "-c",
        "--client",
        help="Client IP or VLAN name to test as (default: all VLANs)",
    )
    p_test.add_argument(
        "--type",
        default="A",
        help="DNS record type (default: A)",
    )

    args = parser.parse_args()

    global _json_mode
    _json_mode = args.json

    commands = {
        "logs": cmd_logs,
        "blocked": cmd_blocked,
        "search": cmd_search,
        "test": cmd_test,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
