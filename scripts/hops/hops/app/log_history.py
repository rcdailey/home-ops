"""Container log retrieval for previous instances."""

from __future__ import annotations

from hops.core.format import truncate
from hops.core.runner import run


def previous_container_logs(pod: dict, namespace: str, lines: int) -> str | None:
    """Return previous logs only for containers with a terminated prior instance."""
    status = pod.get("status", {})
    containers = [
        *status.get("containerStatuses", []),
        *status.get("initContainerStatuses", []),
    ]
    restarted = [
        container["name"]
        for container in containers
        if container.get("lastState", {}).get("terminated")
    ]
    if not restarted:
        return None

    chunks = []
    for container_name in restarted:
        result = run(
            [
                "kubectl",
                "logs",
                pod["metadata"]["name"],
                "-n",
                namespace,
                "-c",
                container_name,
                "--previous",
                f"--tail={lines}",
            ],
            timeout=30,
            check=False,
        )
        output = (result.stdout or "").strip()
        if result.returncode != 0:
            stderr = (result.stderr or "kubectl logs failed").strip()
            output = f"(unavailable: {truncate(stderr.splitlines()[0], 120)})"
        chunks.append(f"--- {container_name} ---\n{output or '(none available)'}")

    return "\n".join(chunks)
