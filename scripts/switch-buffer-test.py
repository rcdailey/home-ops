#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Test whether bulk TCP into hanekawa makes its switch port drop a steady stream.

A 40 Mbps UDP probe from Nezuko stands in for a media stream. It runs once alone, then while
Nezuko and the UDM Pro push bulk TCP into hanekawa. Both senders have 10 GbE links, so the
Cluster USW Flex 2.5G port to hanekawa is where the traffic steps down to 2.5 GbE. The iperf3
servers run in a short-lived pod on hanekawa behind a short-lived NodePort Service that keeps
traffic on the node. Senders reach the node IP directly on the LAN, as Silo's NFS reads do; pod
IPs would route through the router instead. The default namespace's Pod Security level rejects
host-network pods.

Background: docs/investigations/2026-11-26-shield-buffering-switch-egress-drops.md
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

NODE = "hanekawa"
NODE_IP = "192.168.1.63"
NAMESPACE = "default"
IMAGE = "networkstatic/iperf3:latest"
NEZUKO_SSH = "nezuko"
ROUTER_SSH = "root@192.168.1.1"
SWITCH_MAC = "a8:9c:6c:80:81:a6"
SWITCH_PORT = 5
# Each iperf3 server listens on its node port so one number serves the pod and the Service. The
# UDP probe also needs TCP on the same port for its iperf3 control connection.
PROBE_PORT = 32201
NEZUKO_BULK_PORT = 32202
ROUTER_BULK_PORT = 32203
PROBE_RATE = "40M"
BULK_STREAMS = 8
BULK_LEAD_SECONDS = 5
POD_READY_SECONDS = 120
# The controller refreshes switch counters about every 75 seconds.
COUNTER_WAIT_SECONDS = 240
COUNTER_POLL_SECONDS = 10
LOCAL_ZONE = ZoneInfo("America/Chicago")


class TestError(Exception):
    """A step failed; the message says which one and why."""


@dataclass(frozen=True)
class PortSample:
    """Cumulative switch port counters as of the controller's last device report."""

    seen: int
    tx_dropped: int
    tx_packets: int


@dataclass(frozen=True)
class Bulk:
    received_bps: float
    retransmits: int


@dataclass(frozen=True)
class Phase:
    name: str
    probe: dict
    bulk: dict[str, Bulk]
    before: PortSample
    after: PortSample


def run(command: list[str], timeout: float, stdin: str | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise TestError(f"{command[0]}: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        raise TestError(f"{shlex.join(command)} failed: {detail}")
    return result.stdout


def ssh(host: str, command: list[str]) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        host,
        shlex.join(command),
    ]


def iperf3_client(port: int, seconds: int, *options: str) -> list[str]:
    return [
        "iperf3",
        "-c",
        NODE_IP,
        "-p",
        str(port),
        "-t",
        str(seconds),
        "-J",
        *options,
    ]


def parse_iperf3(source: str, output: str) -> dict:
    """Return the end summary of an iperf3 JSON report."""
    try:
        report = json.loads(output)
    except json.JSONDecodeError as error:
        raise TestError(f"{source}: iperf3 printed invalid JSON: {error}") from error
    if error := report.get("error"):
        raise TestError(f"{source}: iperf3: {error}")
    return report["end"]


def service_manifest(name: str) -> dict:
    """Expose the servers on the node IP; Local policy keeps traffic on hanekawa."""
    ports = [(PROBE_PORT, "UDP"), (PROBE_PORT, "TCP")]
    ports += [(NEZUKO_BULK_PORT, "TCP"), (ROUTER_BULK_PORT, "TCP")]
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "namespace": NAMESPACE},
        "spec": {
            "type": "NodePort",
            "externalTrafficPolicy": "Local",
            "selector": {"app.kubernetes.io/instance": name},
            "ports": [
                {
                    "name": f"{protocol.lower()}-{port}",
                    "protocol": protocol,
                    "port": port,
                    "nodePort": port,
                }
                for port, protocol in ports
            ],
        },
    }


def pod_manifest(name: str) -> dict:
    hardening = {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": NAMESPACE,
            "labels": {"app.kubernetes.io/instance": name},
        },
        "spec": {
            "nodeName": NODE,
            "restartPolicy": "Never",
            "terminationGracePeriodSeconds": 0,
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 1000,
                "runAsGroup": 1000,
            },
            "containers": [
                {
                    "name": f"iperf3-{port}",
                    "image": IMAGE,
                    "args": ["-s", "-p", str(port)],
                    "securityContext": hardening,
                    # The server creates a temporary file for each test stream.
                    "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
                }
                for port in (PROBE_PORT, NEZUKO_BULK_PORT, ROUTER_BULK_PORT)
            ],
            "volumes": [{"name": "tmp", "emptyDir": {}}],
        },
    }


def wait_for_servers(name: str) -> None:
    """Wait until every iperf3 server runs; fail fast when one exits."""
    deadline = time.monotonic() + POD_READY_SECONDS
    while time.monotonic() < deadline:
        pod = json.loads(
            run(["kubectl", "get", "pod", name, "-n", NAMESPACE, "-o", "json"], 15)
        )
        statuses = pod.get("status", {}).get("containerStatuses", [])
        for status in statuses:
            if terminated := status["state"].get("terminated"):
                logs = run(
                    ["kubectl", "logs", name, "-n", NAMESPACE, "-c", status["name"]], 15
                ).strip()
                reason = terminated.get("reason", "exited")
                raise TestError(f"iperf3 server {status['name']} {reason}: {logs}")
        if len(statuses) == 3 and all(
            "running" in status["state"] for status in statuses
        ):
            return
        time.sleep(2)
    raise TestError(f"iperf3 servers did not start within {POD_READY_SECONDS}s")


def port_sample() -> PortSample:
    output = run(
        ["unifly", "-o", "json", "api", f"api/s/default/stat/device/{SWITCH_MAC}"], 60
    )
    try:
        device = json.loads(output)["data"][0]
        port = next(
            item for item in device["port_table"] if item["port_idx"] == SWITCH_PORT
        )
        return PortSample(device["last_seen"], port["tx_dropped"], port["tx_packets"])
    except (json.JSONDecodeError, KeyError, IndexError, StopIteration) as error:
        raise TestError(f"invalid UniFi controller response: {error}") from error


def port_sample_after(epoch: float) -> PortSample:
    """Wait for the first controller report taken after a phase ended."""
    deadline = time.monotonic() + COUNTER_WAIT_SECONDS
    while time.monotonic() < deadline:
        sample = port_sample()
        if sample.seen >= epoch:
            return sample
        time.sleep(COUNTER_POLL_SECONDS)
    raise TestError(f"switch counters did not refresh within {COUNTER_WAIT_SECONDS}s")


def start_iperf3(host: str, command: list[str]) -> subprocess.Popen[str]:
    try:
        return subprocess.Popen(
            ssh(host, command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as error:
        raise TestError(f"ssh {host}: {error}") from error


def finish_iperf3(source: str, process: subprocess.Popen[str], timeout: float) -> dict:
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise TestError(f"{source}: iperf3 did not finish within {timeout}s") from error
    # iperf3 exits nonzero on test errors but still prints its JSON error report.
    if process.returncode != 0 and not stdout.strip():
        raise TestError(f"{source}: {stderr.strip() or 'ssh failed without output'}")
    return parse_iperf3(source, stdout)


def start_bulk(host: str, port: int, seconds: int) -> subprocess.Popen[str]:
    return start_iperf3(host, iperf3_client(port, seconds, "-P", str(BULK_STREAMS)))


def finish_bulk(source: str, process: subprocess.Popen[str], timeout: float) -> Bulk:
    summary = finish_iperf3(f"{source} bulk", process, timeout)
    return Bulk(
        summary["sum_received"]["bits_per_second"], summary["sum_sent"]["retransmits"]
    )


def run_phase(name: str, seconds: int, before: PortSample, with_load: bool) -> Phase:
    bulk_seconds = seconds + 2 * BULK_LEAD_SECONDS
    senders = {}
    try:
        if with_load:
            senders = {
                "Nezuko": start_bulk(NEZUKO_SSH, NEZUKO_BULK_PORT, bulk_seconds),
                "UDM Pro": start_bulk(ROUTER_SSH, ROUTER_BULK_PORT, bulk_seconds),
            }
            time.sleep(BULK_LEAD_SECONDS)
        probe_command = iperf3_client(PROBE_PORT, seconds, "-u", "-b", PROBE_RATE)
        probe_process = start_iperf3(NEZUKO_SSH, probe_command)
        probe = finish_iperf3("probe", probe_process, seconds + 60)["sum_received"]
        bulk = {
            source: finish_bulk(source, process, bulk_seconds + 60)
            for source, process in senders.items()
        }
    finally:
        for process in senders.values():
            if process.poll() is None:
                process.kill()
    after = port_sample_after(time.time())
    return Phase(name, probe, bulk, before, after)


def clock(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, LOCAL_ZONE).strftime("%H:%M:%S")


def print_phase(phase: Phase, seconds: int) -> None:
    probe = phase.probe
    print(f"{phase.name} ({seconds} s)")
    print(
        f"  probe: {probe['bits_per_second'] / 1e6:.1f} Mbps, "
        f"{probe['lost_packets']} of {probe['packets']} datagrams lost "
        f"({probe['lost_percent']:.2f}%), jitter {probe['jitter_ms']:.3f} ms"
    )
    for source, bulk in phase.bulk.items():
        print(
            f"  {source} bulk: {bulk.received_bps / 1e9:.2f} Gbps received, "
            f"{bulk.retransmits} retransmits"
        )
    drops = phase.after.tx_dropped - phase.before.tx_dropped
    packets = phase.after.tx_packets - phase.before.tx_packets
    print(
        f"  switch port {SWITCH_PORT}: {drops} TX drops of {packets} packets "
        f"(controller reports {clock(phase.before.seen)} to {clock(phase.after.seen)}, "
        "including other traffic on the port)"
    )


def cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure probe loss and switch drops with and without bulk TCP into hanekawa.",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        metavar="SECONDS",
        help="length of each probe run (default: 60)",
    )
    return parser


def main() -> int:
    arguments = cli().parse_args()
    if arguments.duration < 10:
        cli().error("--duration must be at least 10 seconds")
    name = f"switch-buffer-test-{os.getpid()}"
    resources = {
        "apiVersion": "v1",
        "kind": "List",
        "items": [pod_manifest(name), service_manifest(name)],
    }
    try:
        try:
            run(["kubectl", "create", "-f", "-"], 30, json.dumps(resources))
            wait_for_servers(name)
            print(
                f"Path: Nezuko and UDM Pro (10 GbE) -> Cluster USW Flex 2.5G port "
                f"{SWITCH_PORT} -> {NODE} (2.5 GbE)\n",
                flush=True,
            )
            baseline = run_phase("baseline", arguments.duration, port_sample(), False)
            print_phase(baseline, arguments.duration)
            load = run_phase("load", arguments.duration, baseline.after, True)
            print_phase(load, arguments.duration)
        finally:
            # Also cleans up after a partial create, such as a node port already in use.
            subprocess.run(
                [
                    "kubectl",
                    "delete",
                    f"pod/{name}",
                    f"service/{name}",
                    "-n",
                    NAMESPACE,
                    "--ignore-not-found",
                    "--wait=false",
                ],
                capture_output=True,
                timeout=30,
                check=False,
            )
    except TestError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
