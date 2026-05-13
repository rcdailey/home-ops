"""Pod detail diagnostic: container state, previous logs, events.

Implementation of the 'app pod' command, extracted from _diagnose.py
to keep file sizes manageable.
"""

from __future__ import annotations

from hops._format import age_str, info, kv, section, table, truncate
from hops._runner import run, run_json
from hops._workload import resolve_pods, suggest_near_matches


def format_container_state(state: dict) -> tuple[str, str]:
    """Summarize a containerStatus.state dict as (label, detail)."""
    if "running" in state:
        started = state["running"].get("startedAt")
        return "Running", f"started {age_str(started)} ago" if started else ""
    if "terminated" in state:
        t = state["terminated"]
        parts = [f"exit={t.get('exitCode', '?')}"]
        if t.get("reason"):
            parts.append(t["reason"])
        if t.get("finishedAt"):
            parts.append(f"finished {age_str(t['finishedAt'])} ago")
        return "Terminated", " ".join(parts)
    if "waiting" in state:
        w = state["waiting"]
        reason = w.get("reason", "Waiting")
        msg = w.get("message", "")
        return reason, truncate(msg, 80) if msg else ""
    return "?", ""


def diagnose_pod(
    app: str, namespace: str | None, pod_name: str | None, show_events: bool
):
    """Detailed pod state: phase, container timings, event timeline.

    Implementation of the 'app pod' command. Replaces 'kubectl describe pod'
    for diagnosing per-pod lifecycle issues (startup races, image pull delays,
    crash-then-succeed patterns).
    """
    result = resolve_pods(app, namespace)
    if not result:
        hints = suggest_near_matches(app, namespace)
        info(f"error: could not find app {app!r}")
        if hints:
            info(f"  similar: {', '.join(hints)}")
        raise SystemExit(1)
    ns, pods = result

    if pod_name:
        pods = [p for p in pods if p["metadata"]["name"] == pod_name]
    if not pods:
        target = pod_name or app
        info(f"error: no pods matching {target!r} in {ns}")
        raise SystemExit(1)
    pod = pods[0]
    meta = pod["metadata"]
    spec = pod.get("spec", {})
    status = pod.get("status", {})
    name = meta["name"]

    # Summary
    section("POD")
    kv(
        [
            ("name", name),
            ("namespace", ns),
            ("node", spec.get("nodeName", "?")),
            ("phase", status.get("phase", "?")),
            ("age", age_str(meta.get("creationTimestamp"))),
        ]
    )

    # Containers (init + regular)
    init_statuses = status.get("initContainerStatuses", [])
    container_statuses = status.get("containerStatuses", [])
    all_statuses = [("init", cs) for cs in init_statuses] + [
        ("app", cs) for cs in container_statuses
    ]
    if all_statuses:
        section("CONTAINERS")
        rows = []
        for kind, cs in all_statuses:
            cname = cs.get("name", "?")
            restarts = cs.get("restartCount", 0)
            state = cs.get("state", {})
            state_str, detail = format_container_state(state)
            rows.append([kind, cname, str(restarts), state_str, detail])
        table(["KIND", "CONTAINER", "RESTARTS", "STATE", "DETAIL"], rows)

        # Previous termination details (for containers that restarted).
        # Auto-fetch --previous logs for each so the caller sees crash output
        # inline, not after a second command.
        restarted = [
            cs for _, cs in all_statuses if cs.get("lastState", {}).get("terminated")
        ]
        if restarted:
            info("")
            info("Previous terminations:")
            table(
                ["CONTAINER", "EXIT", "REASON", "FINISHED"],
                [
                    [
                        cs.get("name", "?"),
                        str(cs["lastState"]["terminated"].get("exitCode", "?")),
                        cs["lastState"]["terminated"].get("reason", "?"),
                        age_str(cs["lastState"]["terminated"].get("finishedAt")),
                    ]
                    for cs in restarted
                ],
            )
            section("PREVIOUS LOGS")
            for cs in restarted:
                cname = cs.get("name", "?")
                prev = run(
                    [
                        "kubectl",
                        "logs",
                        name,
                        "-n",
                        ns,
                        "-c",
                        cname,
                        "--previous",
                        "--tail=30",
                    ],
                    timeout=15,
                    check=False,
                )
                out = (prev.stdout or "").strip()
                info(f"--- {cname} (previous, last 30 lines) ---")
                print(out if out else "(none available)")

        # Failed containers that never restarted (exit != 0, restartCount == 0).
        # Current logs contain the failure output; no --previous needed.
        failed_no_restart = [
            cs
            for _, cs in all_statuses
            if cs.get("restartCount", 0) == 0
            and cs.get("state", {}).get("terminated", {}).get("exitCode", 0) != 0
        ]
        if failed_no_restart:
            section("FAILURE LOGS")
            for cs in failed_no_restart:
                cname = cs.get("name", "?")
                result = run(
                    ["kubectl", "logs", name, "-n", ns, "-c", cname, "--tail=30"],
                    timeout=15,
                    check=False,
                )
                out = (result.stdout or "").strip()
                info(f"--- {cname} (last 30 lines) ---")
                print(out if out else "(none available)")

    # Events scoped to this specific pod
    if show_events:
        section("EVENTS (pod-scoped)")
        ev_data = run_json(
            [
                "kubectl",
                "get",
                "events",
                "-n",
                ns,
                "--field-selector",
                f"involvedObject.name={name}",
                "--sort-by=.lastTimestamp",
                "-o",
                "json",
            ],
            timeout=15,
        )
        items = ev_data.get("items", [])
        if not items:
            info("(none)")
        else:
            rows = []
            for e in items:
                rows.append(
                    [
                        age_str(e.get("lastTimestamp") or e.get("eventTime")),
                        e.get("type", "?"),
                        e.get("reason", "?"),
                        f"x{e.get('count', 1)}" if e.get("count", 1) > 1 else "",
                        truncate(e.get("message", ""), 100),
                    ]
                )
            table(["AGE", "TYPE", "REASON", "#", "MESSAGE"], rows)
