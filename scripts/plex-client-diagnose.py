#!/usr/bin/env python3

"""Build a compact Plex client incident report for LLM-assisted diagnosis."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SHIELD_NAME = "NVIDIA Shield"
SHIELD_HOST = "192.168.1.105"
PLEX_SERVER_HOST = "192.168.50.100"
SHIELD_LOG_URL = f"http://{SHIELD_HOST}:32500/logging"
LOCAL_ZONE = ZoneInfo("America/Chicago")
HOPS = Path(__file__).with_name("hops.sh")
UNIFI_SSH = Path(__file__).with_name("unifi-ssh.sh")
SWITCH_HOST = "192.168.1.202"
SWITCH_MAC = "24:5a:4c:6e:14:4e"
MEDIA_FLEX_PORT = "6"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_SERVER_EVENTS = 2000
MAX_INCIDENTS = 10
AT_RADIUS = timedelta(minutes=10)
INCIDENT_GAP = timedelta(minutes=3)

SHIELD_LINE = re.compile(
    r"^(?P<month>\d{2})-(?P<day>\d{2}) "
    r"(?P<clock>\d{2}:\d{2}:\d{2}\.\d+)\s+"
    r"(?P<level>[vdiew]): (?P<message>.*)$"
)
DURATION = re.compile(r"^(?P<amount>\d+)(?P<unit>[smhd])$")
INCIDENT_MARKER = re.compile(
    r"(?i)audioTrackUnderrun|bufferingDuration=|Buffering due to network|"
    r"Connection reset by peer|direct play failed|ERROR_CODE_IO_NETWORK|"
    r"playerFailed|Read error at pos|SocketTimeoutException|timeStalled=[1-9]|"
    r"Time out fetching|unable to find a working transcode profile"
)
STALL_SECONDS = re.compile(r"timeStalled=(\d+)")
BUFFERING_METRICS = re.compile(r"bufferingDuration=(\d+), bufferingCount=(\d+)")
TITLE = re.compile(r"\[PlaybackManager] Preparing for (.+)")
URL = re.compile(r"https?://[^\s]+")
USEFUL_QUERY_FIELDS = {
    "hasMDE",
    "location",
    "state",
    "time",
    "timeStalled",
}
TOKEN_PATTERNS = (
    re.compile(r"(?i)(X-Plex-Token(?:=|%3D))[^&\s]+"),
    re.compile(r"(?i)(Authorization:\s*Bearer\s+)[^\s,]+"),
    re.compile(r"(?i)([?&](?:access_)?token=)[^&\s]+"),
)
VOLATILE_VALUE = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f-]{27,}\b|\b\d{4,}\b")
LEVELS = {
    "v": "debug",
    "d": "debug",
    "i": "info",
    "w": "warning",
    "e": "error",
}


@dataclass(frozen=True)
class Event:
    timestamp: datetime
    source: str
    level: str
    message: str
    count: int = 1
    end_timestamp: datetime | None = None


@dataclass(frozen=True)
class CommandResult:
    output: str
    error: str | None = None


@dataclass(frozen=True)
class Incident:
    events: tuple[Event, ...]

    @property
    def start(self) -> datetime:
        return self.events[0].timestamp

    @property
    def end(self) -> datetime:
        return self.events[-1].timestamp


@dataclass(frozen=True)
class NetworkEvidence:
    window_drops: float
    other_switch_drops: float
    speed_changes: float
    peak_bytes_per_second: float
    link_down_count: int
    switch_uptime_seconds: int
    tx_discards: int
    mac_errors: int
    overlapping_incidents: int


def network_assessment(evidence: NetworkEvidence) -> str:
    """Explain whether the Media Flex uplink is the narrowest failure domain."""
    peak_mbps = evidence.peak_bytes_per_second * 8 / 1_000_000
    days = evidence.switch_uptime_seconds / 86400
    link_downs_per_day = evidence.link_down_count / days if days else 0
    overlap = "incident" if evidence.overlapping_incidents == 1 else "incidents"
    if evidence.window_drops and not evidence.other_switch_drops:
        integrity = (
            "zero MAC errors"
            if evidence.mac_errors == 0
            else f"{evidence.mac_errors} MAC errors"
        )
        speed = (
            "no sampled speed changes"
            if evidence.speed_changes == 0
            else f"{evidence.speed_changes:g} sampled speed changes"
        )
        saturation = (
            "sustained bandwidth saturation was not the cause"
            if peak_mbps < 800
            else "possibly bandwidth saturation"
        )
        return (
            "The Media Flex uplink is the strongest failure domain: it dropped "
            f"{evidence.window_drops:g} transmitted packets during the window, and the "
            f"drop bursts overlapped {evidence.overlapping_incidents} {overlap}. Other "
            f"Switch Pro 48 ports had no drops. The link had {integrity} and {speed}; "
            f"its {peak_mbps:.0f} Mbps peak indicates {saturation}. Its long-term "
            f"link-down rate is {link_downs_per_day:.1f}/day."
        )
    return "UniFi counters do not isolate the failure to the Media Flex uplink."


def redact(message: str) -> str:
    """Remove credentials that can appear in Plex request logs."""
    for pattern in TOKEN_PATTERNS:
        message = pattern.sub(r"\1[REDACTED]", message)
    return message


def infer_timestamp(match: re.Match[str], reference: datetime) -> datetime:
    """Infer the missing year from the incident window."""
    clock = match.group("clock")
    month = int(match.group("month"))
    day = int(match.group("day"))
    parsed_time = time.fromisoformat(clock)
    candidates = []
    for year in (reference.year - 1, reference.year, reference.year + 1):
        value = datetime(
            year,
            month,
            day,
            parsed_time.hour,
            parsed_time.minute,
            parsed_time.second,
            parsed_time.microsecond,
            tzinfo=LOCAL_ZONE,
        )
        candidates.append(value)
    return min(candidates, key=lambda value: abs(value - reference))


def compact_stack_trace(message: str) -> str:
    """Replace verbose Java frames with a frame count."""
    lines = message.splitlines()
    frames = sum(line.lstrip().startswith("at ") for line in lines)
    meaningful = [line.strip() for line in lines if not line.lstrip().startswith("at ")]
    result = " ".join(part for part in meaningful if part)
    if frames:
        noun = "frame" if frames == 1 else "frames"
        result = f"{result} [{frames} stack {noun} omitted]"
    return result


def parse_shield_events(text: str, reference: datetime) -> list[Event]:
    """Parse Plex Android logs, including multiline exception records."""
    events: list[Event] = []
    current: Event | None = None

    for line in text.splitlines():
        match = SHIELD_LINE.match(line)
        if match:
            if current is not None:
                events.append(
                    replace(current, message=compact_stack_trace(current.message))
                )
            current = Event(
                timestamp=infer_timestamp(match, reference),
                source="client",
                level=LEVELS[match.group("level")],
                message=match.group("message"),
            )
            continue
        if current is not None:
            current = replace(current, message=f"{current.message}\n{line}")

    if current is not None:
        events.append(replace(current, message=compact_stack_trace(current.message)))
    return events


def parse_server_events(output: str) -> list[Event]:
    """Parse the NDJSON records emitted by Hops while ignoring its summary."""
    events = []
    for line in output.splitlines():
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
            timestamp = datetime.fromisoformat(record["_time"].replace("Z", "+00:00"))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        log_file = str(record.get("log_file", ""))
        if log_file.startswith("Plex Transcoder Statistics"):
            continue
        events.append(
            Event(
                timestamp=timestamp.astimezone(LOCAL_ZONE),
                source="server",
                level=str(record.get("level", "unknown")).lower(),
                message=str(record.get("_msg", record.get("message", ""))),
            )
        )
    return events


def compact_url(match: re.Match[str]) -> str:
    """Keep only request fields that explain playback behavior."""
    value = match.group(0)
    parsed = urllib.parse.urlsplit(value)
    query = [
        (key, item)
        for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key in USEFUL_QUERY_FIELDS
    ]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), "")
    )


def clean_message(message: str) -> str:
    """Prepare a bounded single-line message for compact output."""
    message = redact(message)
    message = URL.sub(compact_url, message)
    message = re.sub(r"\s+", " ", message).strip()
    if len(message) <= 320:
        return message
    return f"{message[:317]}..."


def compact_events(events: list[Event]) -> list[Event]:
    """Collapse repeated records without losing their first example or time span."""
    compacted: list[Event] = []
    positions: dict[tuple[str, str, str], int] = {}
    for event in sorted(events, key=lambda item: item.timestamp):
        event = replace(event, message=clean_message(event.message))
        signature = (
            event.source,
            event.level,
            VOLATILE_VALUE.sub("#", event.message),
        )
        if signature in positions:
            position = positions[signature]
            previous = compacted[position]
            compacted[position] = replace(
                previous,
                count=previous.count + 1,
                end_timestamp=event.timestamp,
            )
            continue
        positions[signature] = len(compacted)
        compacted.append(event)
    return compacted


def detect_incidents(events: list[Event]) -> list[Incident]:
    """Group explicit buffering and delivery failures into bounded episodes."""
    markers = compact_events([event for event in events if is_incident_marker(event)])
    incidents: list[Incident] = []
    current: list[Event] = []
    for event in markers:
        if current and event.timestamp - current[-1].timestamp > INCIDENT_GAP:
            incidents.append(Incident(tuple(current)))
            current = []
        if not current and is_secondary_marker(event):
            continue
        current.append(event)
    if current:
        incidents.append(Incident(tuple(current)))
    return incidents


def is_incident_marker(event: Event) -> bool:
    """Exclude unrelated internet requests from playback delivery incidents."""
    if not INCIDENT_MARKER.search(event.message):
        return False
    if "Time out fetching" in event.message:
        return PLEX_SERVER_HOST in event.message
    return True


def is_secondary_marker(event: Event) -> bool:
    """Return markers that explain an active incident but cannot start one."""
    message = event.message
    return "bufferingDuration=" in message or "working transcode profile" in message


def incident_title(incident: Incident, events: list[Event]) -> str | None:
    """Find the most recent title prepared before an incident."""
    candidates = []
    for event in events:
        match = TITLE.search(event.message)
        if not match or event.timestamp > incident.end:
            continue
        if incident.end - event.timestamp > timedelta(minutes=45):
            continue
        candidates.append((event.timestamp, match.group(1)))
    if not candidates:
        return None
    return max(candidates)[1]


def incident_cause(incident: Incident) -> str:
    """Classify the narrowest cause supported by client evidence."""
    text = "\n".join(event.message for event in incident.events).lower()
    network_markers = (
        "network too slow",
        "network_connection_timeout",
        "sockettimeoutexception",
        "time out fetching",
    )
    if any(marker in text for marker in network_markers):
        return "network or server delivery path"
    if "direct play failed" in text or "read error at pos" in text:
        return "media delivery or demux path"
    if "playerfailed" in text:
        return "Shield player lifecycle"
    return "playback delivery path"


def summarize_incident(incident: Incident, events: list[Event]) -> str:
    """Explain one incident using counts instead of raw repetitive records."""
    cause = incident_cause(incident)
    messages = [event.message for event in incident.events]
    facts = []

    stalls = [
        int(match.group(1))
        for message in messages
        if (match := STALL_SECONDS.search(message))
    ]
    if stalls:
        seconds = max(stalls)
        unit = "second" if seconds == 1 else "seconds"
        facts.append(f"the spinner was reported for at least {seconds} {unit}")

    underruns = sum(
        event.count
        for event in incident.events
        if "audioTrackUnderrun" in event.message
    )
    if underruns:
        facts.append(f"{underruns} audio underruns followed")

    metrics = [
        (int(match.group(1)), int(match.group(2)))
        for message in messages
        if (match := BUFFERING_METRICS.search(message))
    ]
    if metrics:
        duration, count = max(metrics)
        facts.append(
            f"the session recorded {duration / 1000:.1f}s across {count} buffers"
        )

    text = "\n".join(messages).lower()
    if "direct play failed" in text:
        facts.append("direct play failed and Plex fell back to transcoding")
    if "unable to find a working transcode profile" in text:
        facts.append("the server also rejected transcode profiles")
    if "network too slow" in text:
        facts.append("the client explicitly reported that the network was too slow")

    title = incident_title(incident, events)
    subject = f" while playing {title}" if title else ""
    detail = "; ".join(facts) if facts else "the client recorded a playback failure"
    return f"Likely {cause}{subject}: {detail}."


def incident_evidence(incident: Incident) -> list[Event]:
    """Return a small representative evidence set for one incident."""
    events = list(incident.events)
    selected = []

    def first_containing(*markers: str) -> Event | None:
        return next(
            (
                event
                for event in events
                if any(marker in event.message.lower() for marker in markers)
            ),
            None,
        )

    selected.extend(
        filter(
            None,
            (
                first_containing("network too slow"),
                first_containing(
                    "network_connection_timeout", "sockettimeoutexception"
                ),
                first_containing("time out fetching"),
                first_containing("direct play failed"),
                first_containing("working transcode profile"),
            ),
        )
    )

    stalled = [event for event in events if STALL_SECONDS.search(event.message)]
    if stalled:

        def stalled_seconds(event: Event) -> int:
            match = STALL_SECONDS.search(event.message)
            return int(match.group(1)) if match else 0

        selected.append(max(stalled, key=stalled_seconds))
    buffering = [event for event in events if BUFFERING_METRICS.search(event.message)]
    if buffering:

        def buffering_duration(event: Event) -> int:
            match = BUFFERING_METRICS.search(event.message)
            return int(match.group(1)) if match else 0

        selected.append(max(buffering, key=buffering_duration))
    if underrun := first_containing("audiotrackunderrun"):
        selected.append(underrun)

    unique = {(event.timestamp, event.message): event for event in selected}
    return sorted(unique.values(), key=lambda event: event.timestamp)[:6]


def overall_assessment(incidents: list[Incident]) -> str:
    """State the strongest conclusion shared by the incident set."""
    if not incidents:
        return "No explicit buffering or delivery failure was found in the selected window."
    delivery = sum(
        incident_cause(incident) == "network or server delivery path"
        for incident in incidents
    )
    if delivery:
        return (
            f"{delivery} of {len(incidents)} incidents point to delivery between the Shield "
            "and Plex. The logs cannot distinguish a LAN interruption from Plex or NFS "
            "failing to supply media bytes, so those paths need correlation at the same times."
        )
    return "The incidents are client-side playback failures without direct network evidence."


def fetch_shield_logs() -> str:
    """Fetch the Shield's bounded Plex network-log snapshot."""
    request = urllib.request.Request(
        SHIELD_LOG_URL,
        headers={"User-Agent": "plex-client-diagnose"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise RuntimeError("Shield response exceeded the 16 MiB safety limit")
    return data.decode("utf-8", "replace")


def run_hops(*arguments: str) -> CommandResult:
    """Run one bounded cluster query through Hops."""
    try:
        result = subprocess.run(
            [str(HOPS), *arguments],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return CommandResult("", str(error))
    if result.returncode == 0:
        return CommandResult(result.stdout.strip())
    detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
    return CommandResult("", detail)


def latest_query_value(output: str) -> float:
    """Sum the latest value from each VictoriaMetrics result series."""
    payload = json.loads(output)
    total = 0.0
    results = payload["data"]["result"]
    for result in results:
        if values := result.get("values"):
            total += float(values[-1][1])
        elif value := result.get("value"):
            total += float(value[1])
    return total


def query_counter(promql: str, end: datetime) -> tuple[float | None, str | None]:
    """Run an instant counter query through Hops."""
    result = run_hops(
        "query",
        "query",
        promql,
        "--at",
        end.isoformat(),
        "--window",
        "1m",
        "--json",
    )
    if result.error:
        return None, result.error
    try:
        return latest_query_value(result.output), None
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        return None, f"invalid VictoriaMetrics response: {error}"


def query_series(
    promql: str,
    start: datetime,
    end: datetime,
) -> tuple[list[tuple[datetime, float]], str | None]:
    """Run a range query and flatten its timestamped values."""
    result = run_hops(
        "query",
        "query",
        promql,
        "--from",
        start.isoformat(),
        "--to",
        end.isoformat(),
        "--step",
        "30s",
        "--json",
    )
    if result.error:
        return [], result.error
    try:
        payload = json.loads(result.output)
        values = []
        for series in payload["data"]["result"]:
            values.extend(
                (datetime.fromtimestamp(item[0], LOCAL_ZONE), float(item[1]))
                for item in series.get("values", [])
            )
        return values, None
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        return [], f"invalid VictoriaMetrics response: {error}"


def current_media_flex_port() -> tuple[dict | None, str | None]:
    """Read current controller counters for the Media Flex uplink."""
    try:
        result = subprocess.run(
            [
                "unifly",
                "-o",
                "json",
                "api",
                f"api/s/default/stat/device/{SWITCH_MAC}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, str(error)
    if result.returncode != 0:
        return None, result.stderr.strip() or result.stdout.strip()
    try:
        device = json.loads(result.stdout)["data"][0]
        port = next(
            item
            for item in device["port_table"]
            if str(item.get("port_idx")) == MEDIA_FLEX_PORT
        )
        return {"uptime": device["uptime"], "port": port}, None
    except (json.JSONDecodeError, KeyError, StopIteration, TypeError) as error:
        return None, f"invalid UniFi controller response: {error}"


def switch_mac_counters() -> tuple[dict | None, str | None]:
    """Confirm low-level port discards and MAC errors over SSH."""
    try:
        result = subprocess.run(
            [
                str(UNIFI_SSH),
                "-f",
                "Error|Discard|Collision",
                SWITCH_HOST,
                "swctrl",
                "port",
                "show",
                "counters",
                "id",
                MEDIA_FLEX_PORT,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, str(error)
    if result.returncode != 0:
        return None, result.stderr.strip() or result.stdout.strip()

    discard_match = re.search(r"TX Pkt Discard:\s+(\d+)", result.stdout)
    error_lines = [line for line in result.stdout.splitlines() if "Error" in line]
    errors = sum(
        int(value) for line in error_lines for value in re.findall(r":\s+(\d+)", line)
    )
    if not discard_match:
        return None, "switch output omitted TX packet discards"
    return {"tx_discards": int(discard_match.group(1)), "mac_errors": errors}, None


def collect_network_evidence(
    start: datetime,
    end: datetime,
    incidents: list[Incident],
) -> tuple[NetworkEvidence | None, list[str]]:
    """Correlate UniFi port counters with detected playback incidents."""
    seconds = max(1, int((end - start).total_seconds()))
    selector = f'name="Switch Pro 48",port_num="{MEDIA_FLEX_PORT}"'
    queries = {
        "window_drops": (
            "increase(unpoller_device_port_transmit_dropped_total{"
            f"{selector}" + f"}}[{seconds}s])"
        ),
        "all_switch_drops": (
            "sum(increase(unpoller_device_port_transmit_dropped_total{"
            'name="Switch Pro 48"' + f"}}[{seconds}s]))"
        ),
        "speed_changes": (
            "changes(unpoller_device_port_port_speed_bps{"
            f"{selector}" + f"}}[{seconds}s])"
        ),
        "peak_bytes_per_second": (
            "max_over_time(unpoller_device_port_transmit_rate_bytes{"
            f"{selector}" + f"}}[{seconds}s])"
        ),
    }
    values = {}
    errors = []
    for name, query in queries.items():
        value, error = query_counter(query, end)
        if error:
            errors.append(f"UniFi {name.replace('_', ' ')} unavailable: {error}.")
            continue
        values[name] = value or 0

    burst_query = (
        f"increase(unpoller_device_port_transmit_dropped_total{{{selector}" + "}[1m])"
    )
    bursts, burst_error = query_series(burst_query, start, end)
    if burst_error:
        errors.append(f"UniFi drop timeline unavailable: {burst_error}.")

    controller, controller_error = current_media_flex_port()
    if controller_error:
        errors.append(f"UniFi port state unavailable: {controller_error}.")
    mac, mac_error = switch_mac_counters()
    if mac_error:
        errors.append(f"UniFi switch counters unavailable: {mac_error}.")
    if errors or controller is None or mac is None:
        return None, errors

    overlap = sum(
        any(
            value > 0
            and incident.start - timedelta(minutes=1)
            <= timestamp
            <= incident.end + timedelta(minutes=1)
            for timestamp, value in bursts
        )
        for incident in incidents
    )
    port = controller["port"]
    window_drops = values["window_drops"]
    return (
        NetworkEvidence(
            window_drops=window_drops,
            other_switch_drops=max(0, values["all_switch_drops"] - window_drops),
            speed_changes=values["speed_changes"],
            peak_bytes_per_second=values["peak_bytes_per_second"],
            link_down_count=int(port.get("link_down_count", 0)),
            switch_uptime_seconds=int(controller["uptime"]),
            tx_discards=int(mac["tx_discards"]),
            mac_errors=int(mac["mac_errors"]),
            overlapping_incidents=overlap,
        ),
        [],
    )


def summarize_metric(name: str, output: str) -> str:
    """Turn Hops metric lines into one compact sentence."""
    values = []
    for line in output.splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        label = label.strip().lower()
        if label.startswith("max"):
            label = "maximum"
        elif label.startswith("avg"):
            label = "average"
        elif label.startswith("current"):
            label = "current"
        values.append(f"{label} {value.strip()}")
    if not values:
        return f"{name}: no samples returned."
    return f"{name}: {'; '.join(values)}."


def summarize_resources(output: str) -> str | None:
    """Extract Plex limits from the compact Hops resource table."""
    for line in output.splitlines():
        fields = line.split()
        if len(fields) != 8 or fields[1] != "app":
            continue
        if not fields[0].startswith("plex-") or fields[0].startswith("plexanisync-"):
            continue
        cpu_limit = "no CPU limit" if fields[4] == "-" else f"CPU limit {fields[4]}"
        return f"Server limits: {cpu_limit}; memory limit {fields[7]}."
    return None


def maximum_metric(output: str) -> str | None:
    """Extract the maximum value from Hops metric prose."""
    for line in output.splitlines():
        if line.lower().startswith("max") and ":" in line:
            return line.split(":", 1)[1].strip()
    return None


def resource_assessment(
    metric_results: dict[str, CommandResult],
    resource_summary: str | None,
) -> str | None:
    """Explain whether container limits support a resource-pressure cause."""
    if not resource_summary or "no CPU limit" not in resource_summary:
        return None
    cpu_max = maximum_metric(metric_results["CPU"].output)
    memory_max = maximum_metric(metric_results["Memory"].output)
    if not cpu_max or not memory_max:
        return None
    memory_limit = resource_summary.rsplit("memory limit ", 1)[-1].rstrip(".")
    return (
        "Plex container pressure is not supported by these metrics: CPU peaked at "
        f"{cpu_max} with no CPU limit, and memory peaked at {memory_max} of "
        f"{memory_limit}."
    )


def client_connection(events: list[Event]) -> str | None:
    """Report the transport selected by the Shield when logged."""
    for event in reversed(events):
        if "Device is under Ethernet" in event.message:
            return "The Shield reported using Ethernet during the selected window."
        if "Device is under WiFi" in event.message:
            return "The Shield reported using Wi-Fi during the selected window."
    return None


def parse_duration(value: str) -> timedelta:
    """Parse a compact positive duration accepted by Hops."""
    match = DURATION.fullmatch(value)
    if not match:
        raise argparse.ArgumentTypeError(
            "use a positive duration such as 30m, 2h, or 1d"
        )
    amount = int(match.group("amount"))
    if amount == 0:
        raise argparse.ArgumentTypeError("duration must be greater than zero")
    factors = {
        "s": timedelta(seconds=amount),
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
    }
    return factors[match.group("unit")]


def parse_at(value: str) -> datetime:
    """Parse a local or explicitly zoned incident timestamp."""
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "use an ISO timestamp such as 2026-08-27 19:40"
        ) from error
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=LOCAL_ZONE)
    return timestamp.astimezone(LOCAL_ZONE)


def cli() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Correlate Shield Plex logs with cluster logs and metrics.",
    )
    window = parser.add_mutually_exclusive_group(required=True)
    window.add_argument(
        "--at",
        type=parse_at,
        help="incident time; inspects ten minutes before and after",
    )
    window.add_argument(
        "--from",
        dest="duration",
        type=parse_duration,
        metavar="DURATION",
        help="look back from now, for example 30m or 2h",
    )
    return parser


def incident_window(
    arguments: argparse.Namespace,
) -> tuple[datetime, datetime, datetime]:
    """Resolve the requested range and its ranking focus."""
    if arguments.at is not None:
        return arguments.at - AT_RADIUS, arguments.at + AT_RADIUS, arguments.at
    end = datetime.now(LOCAL_ZONE)
    return end - arguments.duration, end, end


def format_timestamp(timestamp: datetime, start: datetime, end: datetime) -> str:
    """Omit the date only when the whole report covers one local day."""
    if start.date() == end.date():
        return timestamp.strftime("%H:%M:%S.%f")[:-3]
    return timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def format_event(event: Event, start: datetime, end: datetime) -> str:
    """Render one evidence line."""
    timestamp = format_timestamp(event.timestamp, start, end)
    level = "" if event.level == "info" else f" {event.level}"
    line = f"{timestamp} {event.source}{level}: {event.message}"
    if event.count > 1 and event.end_timestamp is not None:
        through = format_timestamp(event.end_timestamp, start, end)
        line = f"{line} (repeated {event.count} times through {through})"
    return line


def report(arguments: argparse.Namespace) -> int:
    """Collect sources and print an LLM-oriented incident report."""
    start, end, focus = incident_window(arguments)
    from_value = start.isoformat()
    to_value = end.isoformat()
    notes = []
    failures = 0

    try:
        shield_text = fetch_shield_logs()
        client_all = parse_shield_events(shield_text, focus)
        client_window = [
            event for event in client_all if start <= event.timestamp <= end
        ]
    except (OSError, RuntimeError, urllib.error.URLError) as error:
        client_window = []
        notes.append(f"Shield logs unavailable: {error}.")
        failures += 1

    server_result = run_hops(
        "query",
        "logs",
        "query",
        "--app",
        "plex",
        "--from",
        from_value,
        "--to",
        to_value,
        "-n",
        str(MAX_SERVER_EVENTS),
        "--json",
    )
    if server_result.error:
        server_window = []
        notes.append(f"Plex server logs unavailable: {server_result.error}.")
        failures += 1
    else:
        server_window = parse_server_events(server_result.output)

    metric_results = {
        "CPU": run_hops(
            "query",
            "cpu",
            "plex",
            "-c",
            "app",
            "--from",
            from_value,
            "--to",
            to_value,
        ),
        "Memory": run_hops(
            "query",
            "memory",
            "plex",
            "-c",
            "app",
            "--from",
            from_value,
            "--to",
            to_value,
        ),
    }

    metrics = []
    for name, result in metric_results.items():
        if result.error:
            notes.append(f"{name} metrics unavailable: {result.error}.")
            failures += 1
            continue
        metrics.append(summarize_metric(name, result.output))

    range_seconds = max(1, int((end - start).total_seconds()))
    pod_selector = 'namespace="media",pod=~"plex-.*"'
    packet_drop_query = (
        "sum(increase(container_network_receive_packets_dropped_total{"
        f"{pod_selector}" + f"}}[{range_seconds}s])) + "
        "sum(increase(container_network_transmit_packets_dropped_total{"
        f"{pod_selector}" + f"}}[{range_seconds}s]))"
    )
    nfs_retransmit_query = (
        f"sum(increase(node_nfs_rpc_retransmissions_total[{range_seconds}s]))"
    )
    path_counters = {}
    for name, query in (
        ("Plex pod packet drops", packet_drop_query),
        ("Cluster NFS RPC retransmissions", nfs_retransmit_query),
    ):
        value, error = query_counter(query, end)
        if error:
            notes.append(f"{name} unavailable: {error}.")
            failures += 1
            continue
        path_counters[name] = value
        rendered = int(value) if value is not None and value.is_integer() else value
        metrics.append(f"{name}: {rendered} during the window.")

    resources_result = run_hops("app", "resources", "plex")
    resource_summary = None
    if resources_result.error:
        notes.append(f"Plex resource limits unavailable: {resources_result.error}.")
        failures += 1
    elif resource_summary := summarize_resources(resources_result.output):
        metrics.append(resource_summary)

    all_events = sorted(
        [*client_window, *server_window],
        key=lambda event: event.timestamp,
    )
    incidents = detect_incidents(all_events)
    omitted_incidents = max(0, len(incidents) - MAX_INCIDENTS)
    if omitted_incidents:
        incidents = incidents[-MAX_INCIDENTS:]
        notes.append(
            f"Omitted {omitted_incidents} older incidents to keep the report bounded."
        )
    network, network_errors = collect_network_evidence(start, end, incidents)
    if network_errors:
        notes.extend(network_errors)
        failures += 1
    notes.append(
        f"Analyzed {len(client_window)} client and {len(server_window)} server records."
    )

    print("Plex client diagnosis")
    print(
        "Window: "
        f"{start.strftime('%Y-%m-%d %H:%M:%S')} to "
        f"{end.strftime('%Y-%m-%d %H:%M:%S')} America/Chicago"
    )
    print(f"Client: {SHIELD_NAME} at {SHIELD_HOST}")
    print("Server: Plex in the media namespace")

    print("\nAssessment")
    print(overall_assessment(incidents))
    if network:
        print(network_assessment(network))
    if pressure := resource_assessment(metric_results, resource_summary):
        print(pressure)
    if path_counters and all(value == 0 for value in path_counters.values()):
        print(
            "No Plex pod packet drops or NFS RPC retransmissions were recorded. "
            "These counters do not measure switch loss or NFS server latency."
        )
    if connection := client_connection(client_window):
        print(connection)

    print("\nMetrics")
    if metrics:
        for metric in metrics:
            print(metric)
    else:
        print("No metrics were available.")

    if network:
        peak_mbps = network.peak_bytes_per_second * 8 / 1_000_000
        print("\nNetwork path")
        print(
            "Shield -> Media Flex Mini port 2 -> Switch Pro 48 port 6 -> "
            "cluster and Plex"
        )
        print(
            f"Media Flex uplink: {network.window_drops:g} drops in the window; "
            f"{network.tx_discards} lifetime TX discards; {network.mac_errors} MAC errors."
        )
        print(
            f"Other Switch Pro 48 ports: {network.other_switch_drops:g} drops. "
            f"Speed changes: {network.speed_changes:g}. Peak traffic: {peak_mbps:.0f} Mbps."
        )
        print("History: docs/investigations/media-flex-port-flapping-2026-04-18.md")

    print("\nIncidents")
    if incidents:
        for number, incident in enumerate(incidents, 1):
            incident_start = format_timestamp(incident.start, start, end)
            incident_end = format_timestamp(incident.end, start, end)
            print(f"\n{number}. {incident_start} to {incident_end}")
            print(summarize_incident(incident, all_events))
            print("Evidence:")
            for event in incident_evidence(incident):
                print(format_event(event, start, end))
    else:
        print("No explicit buffering or delivery failures were found in this window.")

    if notes:
        print("\nCollection notes")
        for note in notes:
            print(note)
    return 1 if failures else 0


def main() -> None:
    """CLI entry point."""
    arguments = cli().parse_args()
    raise SystemExit(report(arguments))


if __name__ == "__main__":
    main()
