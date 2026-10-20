"""List nodes with health and last working route."""

from __future__ import annotations

import click

from zwave._client import NODE_STATUS, Session, print_json, run


def summarize(node: dict) -> dict:
    stats = node.get("statistics") or {}
    lwr = stats.get("lwr") or {}
    return {
        "id": node["nodeId"],
        "name": node.get("name"),
        "model": node.get("label"),
        "status": NODE_STATUS.get(node.get("status"), node.get("status")),
        "firmware": node.get("firmwareVersion"),
        "rssi": stats.get("rssi"),
        "repeaters": lwr.get("repeaters"),
        "last_seen": stats.get("lastSeen"),
    }


@click.command()
@click.option("--json", "as_json", is_flag=True, help="JSON output")
def cli(as_json: bool) -> None:
    """List nodes: status, firmware, RSSI, and last working route repeaters.

    RSSI and repeaters describe the last successful exchange with the
    controller; empty repeaters means a direct link.
    """

    async def handler(session: Session):
        state = await session.send("start_listening")
        return [summarize(n) for n in state["state"]["nodes"]]

    rows = run(handler)
    if as_json:
        print_json(rows)
        return
    for r in rows:
        route = ",".join(map(str, r["repeaters"])) if r["repeaters"] else "direct"
        if r["repeaters"] is None:
            route = "-"
        rssi = r["rssi"] if r["rssi"] is not None else "-"
        click.echo(
            f"{r['id']:>3}  {r['status']:7}  {rssi!s:>4}  {route:9}  "
            f"{r['model'] or '':16}  {r['name'] or ''}"
        )
