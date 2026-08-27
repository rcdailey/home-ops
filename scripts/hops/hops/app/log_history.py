"""Container log retrieval for previous instances."""

from __future__ import annotations

from hops.core.format import truncate
from hops.core.runner import run

_CRASH_MARKERS = ("fatal", "panic", "error", "permission denied", "oom", "killed")


def compact_crash_logs(output: str, max_lines: int = 20) -> str:
    """Keep the actionable crash line and nearby context instead of a stack tail."""
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if any(marker in line.lower() for marker in _CRASH_MARKERS):
            selected = lines[index : index + max_lines]
            omitted = len(lines) - index - len(selected)
            if omitted > 0:
                selected.append(f"... {omitted} later lines omitted")
            return "\n".join(selected)
    return "\n".join(lines[-max_lines:])


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
