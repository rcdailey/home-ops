"""Compact HTTP request diagnostics for routed applications."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlsplit

import click

from hops.app import cli
from hops.app.gateway import find_httproute
from hops.core.format import info, table, truncate
from hops.core.runner import run


@dataclass
class RequestGroup:
    """Repeated access-log requests with the same observable response."""

    count: int
    first: str
    last: str
    code: int
    method: str
    bytes_sent: int
    client: str
    path: str


def _read_requests(
    hostnames: list[str], since: str, path: str | None, client: str | None
) -> list[dict]:
    """Read and filter Envoy access logs from every gateway replica."""
    result = run(
        [
            "kubectl",
            "logs",
            "-n",
            "network",
            "-l",
            "app.kubernetes.io/name=envoy",
            f"--since={since}",
            "--tail=-1",
            "--all-containers",
        ],
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "kubectl logs failed").strip()
        info(f"error: {message.splitlines()[0]}")
        raise SystemExit(1)

    requests = []
    for line in result.stdout.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get(":authority") not in hostnames:
            continue
        request_path = str(entry.get("x-envoy-origin-path") or "")
        user_agent = str(entry.get("user-agent") or "")
        if path and path not in request_path:
            continue
        if client and client.lower() not in user_agent.lower():
            continue
        requests.append(entry)
    return requests


def _time(value: object) -> str:
    """Keep the date and whole-second UTC time from an Envoy timestamp."""
    timestamp = str(value or "?").replace("T", " ").split(".", maxsplit=1)[0]
    return f"{timestamp}Z" if timestamp != "?" else timestamp


def _group_requests(entries: list[dict]) -> list[RequestGroup]:
    """Group retries while retaining transfer size and first/last timestamps."""
    grouped: dict[tuple[object, ...], RequestGroup] = {}
    for entry in entries:
        raw_path = str(entry.get("x-envoy-origin-path") or "?")
        request_path = urlsplit(raw_path).path
        key = (
            entry.get("response_code", "?"),
            entry.get("method", "?"),
            entry.get("bytes_sent", 0),
            entry.get("user-agent", "?"),
            request_path,
        )
        timestamp = _time(entry.get("start_time"))
        if key not in grouped:
            grouped[key] = RequestGroup(
                count=0,
                first=timestamp,
                last=timestamp,
                code=int(entry.get("response_code", 0)),
                method=str(entry.get("method") or "?"),
                bytes_sent=int(entry.get("bytes_sent", 0)),
                client=str(entry.get("user-agent") or "?"),
                path=request_path,
            )
        group = grouped[key]
        group.count += 1
        group.first = min(group.first, timestamp)
        group.last = max(group.last, timestamp)
    return sorted(grouped.values(), key=lambda group: group.last)


@cli.command("requests")
@click.argument("app")
@click.option(
    "-n", "--namespace", default=None, help="HTTPRoute namespace (auto-detected)"
)
@click.option("--since", default="1h", help="Time window (default: 1h)")
@click.option("--path", default=None, help="Only paths containing this text")
@click.option("--client", default=None, help="Only user agents containing this text")
@click.option(
    "--limit",
    default=50,
    type=click.IntRange(min=1),
    help="Max grouped requests (default: 50)",
)
def requests(
    app: str,
    namespace: str | None,
    since: str,
    path: str | None,
    client: str | None,
    limit: int,
) -> None:
    """Summarize routed HTTP requests across every gateway replica."""
    route = find_httproute(app, namespace)
    if not route:
        info(f"error: no HTTPRoute matching {app!r}")
        raise SystemExit(1)
    hostnames = route.get("spec", {}).get("hostnames", [])
    if not hostnames:
        info(f"error: HTTPRoute {app!r} has no hostnames")
        raise SystemExit(1)

    entries = _read_requests(hostnames, since, path, client)
    filters = []
    if path:
        filters.append(f"path={path!r}")
    if client:
        filters.append(f"client={client!r}")
    suffix = f" ({', '.join(filters)})" if filters else ""
    if not entries:
        info(f"No requests to {', '.join(hostnames)} in the last {since}{suffix}.")
        return

    statuses = Counter(int(entry.get("response_code", 0)) for entry in entries)
    status_text = ", ".join(
        f"{code}={count}" for code, count in sorted(statuses.items())
    )
    info(f"Host: {', '.join(hostnames)}")
    info(f"Requests: {len(entries)} in {since}{suffix}; status {status_text}")

    groups = _group_requests(entries)[-limit:]
    rows = [
        [
            str(group.count),
            str(group.code),
            group.method,
            str(group.bytes_sent),
            group.first,
            group.last,
            truncate(group.client, 24),
            truncate(group.path, 80),
        ]
        for group in groups
    ]
    table(["#", "CODE", "METHOD", "BYTES", "FIRST", "LAST", "CLIENT", "PATH"], rows)
