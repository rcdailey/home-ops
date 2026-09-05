"""Correlate VolSync sources, Kopia snapshots, and workload mounts."""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any, Never

import click

from hops.core.format import age_str, human_bytes, info, kv, section, table
from hops.core.runner import kubectl_exec, kubectl_json

_LIST_LINE = re.compile(
    r"^(?P<mode>\S+)\s+(?P<size>\d+)\s+"
    r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+\S+\s+(?P<name>.*)$"
)


def list_backups(namespaces: tuple[str, ...], sort_by: str) -> None:
    """List the latest snapshot per Kopia source, largest first."""
    snapshots = _kopia_json(
        ["snapshot", "list", "--all", "--json", "--max-results", "1"]
    )
    namespace_filter = set(namespaces)
    rows = []
    for snapshot in snapshots:
        source = snapshot.get("source", {})
        namespace = source.get("host", "?")
        if namespace_filter and namespace not in namespace_filter:
            continue
        rows.append(
            {
                "pod": source.get("userName", "?"),
                "namespace": namespace,
                "size": int(snapshot.get("stats", {}).get("totalSize", 0)),
                "endTime": snapshot.get("endTime", ""),
            }
        )
    if sort_by == "last-snapshot":
        rows.sort(key=lambda row: row["endTime"])
    else:
        rows.sort(key=lambda row: row["size"], reverse=True)
    if not rows:
        info("No Kopia backups found.")
        return
    table(
        ["POD", "NAMESPACE", "SIZE", "LAST SNAPSHOT"],
        [
            [
                row["pod"],
                row["namespace"],
                human_bytes(row["size"]),
                f"{age_str(row['endTime'])} ago",
            ]
            for row in rows
        ],
    )


def inspect_backup(
    app: str,
    namespace: str | None,
    path: str,
    limit: int,
    as_json: bool,
) -> None:
    """Inspect the latest Kopia snapshot for a VolSync source."""
    source = _resolve_source(app, namespace)
    source_meta = source.get("metadata", {})
    source_spec = source.get("spec", {})
    name = source_meta.get("name", "")
    ns = source_meta.get("namespace", "")
    pvc = source_spec.get("sourcePVC", "")

    snapshots = _kopia_json(
        ["snapshot", "list", "--all", "--json", "--max-results", "1"]
    )
    matching = [
        item
        for item in snapshots
        if item.get("source", {}).get("userName") == name
        and item.get("source", {}).get("host") == ns
    ]
    if not matching:
        _fail(f"no Kopia snapshot found for {name}@{ns}")
    snapshot = max(matching, key=lambda item: item.get("endTime", ""))

    normalized_path = _normalize_path(path)
    root = snapshot.get("rootEntry", {})
    object_id = root.get("obj", "")
    if not object_id:
        _fail(f"snapshot {snapshot.get('id', '?')} has no root object")
    object_path = f"{object_id}/{normalized_path}" if normalized_path else object_id
    entries = _parse_entries(_kopia_text(["ls", "-l", object_path]))
    entries.sort(key=lambda entry: entry["sizeBytes"], reverse=True)
    shown_entries = entries[:limit]
    listed_size = sum(entry["sizeBytes"] for entry in entries)
    mounts = _pvc_mounts(pvc, ns)

    result = {
        "source": {
            "name": name,
            "namespace": ns,
            "pvc": pvc,
            "copyMethod": source_spec.get("kopia", {}).get("copyMethod", ""),
        },
        "snapshot": {
            "id": snapshot.get("id", ""),
            "endTime": snapshot.get("endTime", ""),
            "totalSizeBytes": snapshot.get("stats", {}).get("totalSize", 0),
            "fileCount": _snapshot_file_count(snapshot),
            "errorCount": snapshot.get("stats", {}).get("errorCount", 0),
        },
        "path": normalized_path or "/",
        "listedSizeBytes": listed_size,
        "entries": shown_entries,
        "truncatedEntries": max(0, len(entries) - len(shown_entries)),
        "mounts": mounts,
    }
    if as_json:
        click.echo(json.dumps(result, separators=(",", ":")))
        return
    _print_result(result)


def _resolve_source(app: str, namespace: str | None) -> dict[str, Any]:
    data = kubectl_json("replicationsources.volsync.backube", namespace=namespace)
    items = data.get("items", [])
    exact = [item for item in items if item.get("metadata", {}).get("name") == app]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        namespaces = sorted(item["metadata"]["namespace"] for item in exact)
        _fail(f"backup source {app!r} is ambiguous; use -n ({', '.join(namespaces)})")
    names = sorted(
        {
            item.get("metadata", {}).get("name", "")
            for item in items
            if app.lower() in item.get("metadata", {}).get("name", "").lower()
        }
    )
    suffix = f"; similar: {', '.join(names)}" if names else ""
    _fail(f"could not find backup source {app!r}{suffix}")


def _kopia_json(args: list[str]) -> Any:
    output = _kopia_text(args)
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        _fail(f"failed to parse Kopia JSON: {exc}")


def _kopia_text(args: list[str]) -> str:
    result = kubectl_exec(
        "deploy/kopia",
        ["kopia", *args],
        namespace="storage",
        container="app",
        timeout=120,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "Kopia command failed").strip()
        _fail(message.splitlines()[0])
    return result.stdout


def _normalize_path(path: str) -> str:
    stripped = path.strip("/")
    if not stripped:
        return ""
    normalized = PurePosixPath(stripped)
    if normalized.is_absolute() or ".." in normalized.parts:
        _fail("path must stay within the snapshot root")
    return str(normalized)


def _parse_entries(output: str) -> list[dict[str, Any]]:
    entries = []
    for line in output.splitlines():
        match = _LIST_LINE.match(line)
        if not match:
            continue
        mode = match.group("mode")
        kind = "directory" if mode.startswith("d") else "file"
        if mode.startswith("L"):
            kind = "symlink"
        entries.append(
            {
                "name": match.group("name").rstrip("/"),
                "kind": kind,
                "sizeBytes": int(match.group("size")),
            }
        )
    if not entries and output.strip():
        _fail("Kopia returned an unrecognized directory listing")
    return entries


def _snapshot_file_count(snapshot: dict[str, Any]) -> int:
    summary = snapshot.get("rootEntry", {}).get("summ", {})
    return int(summary.get("files", 0)) + int(summary.get("symlinks", 0))


def _pvc_mounts(pvc: str, namespace: str) -> list[dict[str, str]]:
    pods = kubectl_json("pods", namespace=namespace).get("items", [])
    mounts: set[tuple[str, str, str]] = set()
    for pod in pods:
        spec = pod.get("spec", {})
        volume_names = {
            volume.get("name", "")
            for volume in spec.get("volumes", [])
            if volume.get("persistentVolumeClaim", {}).get("claimName") == pvc
        }
        if not volume_names:
            continue
        labels = pod.get("metadata", {}).get("labels", {})
        workload = labels.get("app.kubernetes.io/name")
        workload = workload or pod.get("metadata", {}).get("name", "?")
        containers = spec.get("initContainers", []) + spec.get("containers", [])
        for container in containers:
            for mount in container.get("volumeMounts", []):
                if mount.get("name") in volume_names:
                    mounts.add(
                        (
                            workload,
                            container.get("name", "?"),
                            mount.get("mountPath", "?"),
                        )
                    )
    return [
        {"workload": workload, "container": container, "path": path}
        for workload, container, path in sorted(mounts)
    ]


def _print_result(result: dict[str, Any]) -> None:
    source = result["source"]
    snapshot = result["snapshot"]
    section("BACKUP")
    kv(
        [
            ("source", f"{source['namespace']}/{source['name']}"),
            ("pvc", source["pvc"]),
            ("copy", source["copyMethod"] or "?"),
            ("snapshot", snapshot["id"]),
            ("completed", f"{age_str(snapshot['endTime'])} ago"),
            ("logical size", human_bytes(snapshot["totalSizeBytes"])),
            ("files", str(snapshot["fileCount"])),
            ("errors", str(snapshot["errorCount"])),
        ]
    )
    section("MOUNTS")
    mounts = result["mounts"]
    if mounts:
        table(
            ["WORKLOAD", "CONTAINER", "PATH"],
            [[item["workload"], item["container"], item["path"]] for item in mounts],
        )
    else:
        info("No running pod mounts this PVC.")

    section(f"CONTENTS {result['path']}")
    listed_size = result["listedSizeBytes"]
    rows = []
    for entry in result["entries"]:
        percent = entry["sizeBytes"] / listed_size * 100 if listed_size else 0
        rows.append(
            [
                entry["kind"],
                human_bytes(entry["sizeBytes"]),
                f"{percent:.1f}%",
                entry["name"],
            ]
        )
    table(["TYPE", "SIZE", "%", "NAME"], rows)
    if result["truncatedEntries"]:
        info(f"... {result['truncatedEntries']} more entries; increase --limit")


def _fail(message: str) -> Never:
    click.echo(f"error: {message}", err=True)
    raise SystemExit(1)
