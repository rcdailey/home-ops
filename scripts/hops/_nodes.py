"""Node name/IP resolution, cached per process."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from hops._runner import run_json


@dataclass
class Node:
    name: str
    ip: str
    role: str
    status: str
    kubelet: str
    kernel: str


_cache: list[Node] | None = None


def _fetch() -> list[Node]:
    data = run_json(["kubectl", "get", "nodes", "-o", "json"])
    nodes = []
    for item in data.get("items", []):
        meta = item.get("metadata", {})
        labels = meta.get("labels", {})
        status = item.get("status", {})

        name = meta.get("name", "")

        # IP from status.addresses
        ip = ""
        for addr in status.get("addresses", []):
            if addr.get("type") == "InternalIP":
                ip = addr.get("address", "")
                break

        # Role from labels
        role = "worker"
        if "node-role.kubernetes.io/control-plane" in labels:
            role = "cp"

        # Ready condition
        ready = "Unknown"
        for cond in status.get("conditions", []):
            if cond.get("type") == "Ready":
                ready = "Ready" if cond.get("status") == "True" else "NotReady"
                break

        info = status.get("nodeInfo", {})
        kubelet = info.get("kubeletVersion", "")
        kernel = info.get("kernelVersion", "")

        nodes.append(
            Node(
                name=name,
                ip=ip,
                role=role,
                status=ready,
                kubelet=kubelet,
                kernel=kernel,
            )
        )
    return nodes


def get_all() -> list[Node]:
    """Return all nodes, cached after first call."""
    global _cache
    if _cache is None:
        _cache = _fetch()
    return _cache


def resolve_ip(name_or_ip: str) -> str:
    """Resolve a node name to its IP address. Passthrough if already an IP."""
    if any(c.isalpha() for c in name_or_ip):
        for node in get_all():
            if node.name == name_or_ip:
                return node.ip
        return name_or_ip
    return name_or_ip


def resolve_name(ip: str) -> str:
    """Resolve a node IP to its name. Passthrough if already a name."""
    if not any(c.isalpha() for c in ip):
        for node in get_all():
            if node.ip == ip:
                return node.name
    return ip


def resolve_ips(names: Sequence[str] | None = None) -> list[str]:
    """Resolve node names to IPs. If names is None, return all node IPs."""
    if names is None:
        return [n.ip for n in get_all()]
    return [resolve_ip(n) for n in names]
