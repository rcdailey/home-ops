"""Shared subprocess runner with error handling and JSON parsing."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any


def run(
    args: list[str],
    *,
    timeout: int = 30,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and return the result.

    On failure, prints a one-line error and exits non-zero.
    """
    try:
        return subprocess.run(
            args,
            capture_output=capture,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        print(f"error: {args[0]} not found in PATH", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print(
            f"error: {args[0]} timed out after {timeout}s",
            file=sys.stderr,
        )
        sys.exit(1)


def run_json(
    args: list[str],
    *,
    timeout: int = 30,
    quiet: bool = False,
) -> Any:
    """Run a subprocess and parse stdout as JSON.

    Returns the parsed object. On failure, prints error and exits.
    When quiet=True, suppresses error output (for probe-style lookups).
    """
    result = run(args, timeout=timeout, check=False)
    if result.returncode != 0:
        if not quiet:
            msg = (result.stderr or result.stdout or "").strip().split("\n")[0]
            print(f"error: {args[0]} failed: {msg}", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        if not quiet:
            print(f"error: failed to parse JSON from {args[0]}: {exc}", file=sys.stderr)
        sys.exit(1)


def run_jsonl(
    args: list[str],
    *,
    timeout: int = 30,
) -> list[Any]:
    """Run a subprocess and parse stdout as concatenated JSON objects.

    Handles tools like talosctl that emit multiple JSON objects
    without array wrapping or newline delimiters.
    """
    result = run(args, timeout=timeout, check=False)
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "").strip().split("\n")[0]
        print(f"error: {args[0]} failed: {msg}", file=sys.stderr)
        sys.exit(1)
    decoder = json.JSONDecoder()
    objects = []
    text = result.stdout.strip()
    pos = 0
    while pos < len(text):
        try:
            obj, end = decoder.raw_decode(text, pos)
            objects.append(obj)
            pos = end
            while pos < len(text) and text[pos] in " \t\r\n":
                pos += 1
        except json.JSONDecodeError as exc:
            print(
                f"error: failed to parse JSON from {args[0]}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
    return objects


def kubectl_json(
    resource: str,
    *extra_args: str,
    namespace: str | None = None,
    timeout: int = 30,
) -> Any:
    """Run kubectl get with JSON output and return parsed data."""
    args = ["kubectl", "get", resource, "-o", "json"]
    if namespace:
        args.extend(["-n", namespace])
    else:
        args.append("--all-namespaces")
    args.extend(extra_args)
    return run_json(args, timeout=timeout)


def kubectl_exec(
    pod_or_deploy: str,
    command: list[str],
    *,
    namespace: str,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run a command inside a pod via kubectl exec."""
    args = ["kubectl", "exec", "-n", namespace, pod_or_deploy, "--"]
    args.extend(command)
    return run(args, timeout=timeout, check=False)


def ceph_json(command: list[str], *, timeout: int = 30) -> Any:
    """Run a ceph command via rook-ceph-tools and parse JSON output."""
    args = [
        "kubectl",
        "exec",
        "-n",
        "rook-ceph",
        "deploy/rook-ceph-tools",
        "--",
        "ceph",
    ]
    args.extend(command)
    args.append("-f")
    args.append("json")
    return run_json(args, timeout=timeout)


def ceph_text(command: list[str], *, timeout: int = 30) -> str:
    """Run a ceph command via rook-ceph-tools and return text output."""
    args = [
        "kubectl",
        "exec",
        "-n",
        "rook-ceph",
        "deploy/rook-ceph-tools",
        "--",
        "ceph",
    ]
    args.extend(command)
    result = run(args, timeout=timeout, check=False)
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "").strip().split("\n")[0]
        print(f"error: ceph failed: {msg}", file=sys.stderr)
        sys.exit(1)
    return result.stdout
