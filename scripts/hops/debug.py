"""Debug domain: ephemeral pod workflows for ad-hoc diagnostics."""

from __future__ import annotations

import os
import sys

import click

from hops._format import info
from hops._runner import run


def _pod_name(prefix: str) -> str:
    return f"hops-{prefix}-{os.getpid()}"


def _run_ephemeral(
    image: str,
    command: list[str],
    *,
    name: str,
    namespace: str = "default",
    timeout: int = 30,
) -> None:
    """Create a pod, wait for completion, capture logs, clean up."""
    create_args = [
        "kubectl",
        "run",
        name,
        "--image",
        image,
        "--restart=Never",
        "--namespace",
        namespace,
        "--override-type=strategic",
        "--overrides",
        '{"spec":{"terminationGracePeriodSeconds":0}}',
        "--command",
        "--",
    ] + command

    try:
        # Create the pod
        result = run(create_args, timeout=timeout, check=False)
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            info(f"error: failed to create pod: {stderr}")
            return

        # Wait for pod to complete (Succeeded or Failed)
        run(
            [
                "kubectl",
                "wait",
                f"pod/{name}",
                "-n",
                namespace,
                "--for=jsonpath={.status.phase}=Succeeded",
                f"--timeout={timeout}s",
            ],
            timeout=timeout + 5,
            check=False,
        )

        # Get logs
        log_result = run(
            ["kubectl", "logs", name, "-n", namespace],
            timeout=15,
            check=False,
        )
        if log_result.stdout:
            print(log_result.stdout.rstrip())
        if log_result.stderr and log_result.returncode != 0:
            print(log_result.stderr.rstrip(), file=sys.stderr)

    finally:
        # Always clean up
        run(
            [
                "kubectl",
                "delete",
                "pod",
                name,
                "-n",
                namespace,
                "--grace-period=0",
                "--force",
                "--wait=false",
            ],
            timeout=10,
            check=False,
        )


@click.group()
def cli():
    """Ephemeral debug pods for ad-hoc diagnostics."""


@cli.command()
@click.argument("hostname")
@click.option("-n", "--namespace", default="default", help="Namespace to run in")
def dns(hostname: str, namespace: str):
    """DNS lookup via ephemeral busybox pod."""
    name = _pod_name("dns")
    info(f"Resolving {hostname} ...")
    _run_ephemeral(
        image="busybox:stable",
        command=["nslookup", hostname],
        name=name,
        namespace=namespace,
    )


@cli.command()
@click.argument("url")
@click.option("-n", "--namespace", default="default", help="Namespace to run in")
@click.option("--method", default="GET", help="HTTP method")
def curl(url: str, namespace: str, method: str):
    """HTTP request via ephemeral curlimages/curl pod."""
    name = _pod_name("curl")
    info(f"{method} {url} ...")
    _run_ephemeral(
        image="curlimages/curl:latest",
        command=[
            "curl",
            "-sS",
            "-X",
            method,
            "-o",
            "/dev/null",
            "-w",
            "HTTP %{http_code} (%{time_total}s, %{size_download} bytes)\n",
            url,
        ],
        name=name,
        namespace=namespace,
    )
