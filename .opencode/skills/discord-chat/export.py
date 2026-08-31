#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn

DISCORD_EPOCH_MS = 1_420_070_400_000
URL_PATTERN = re.compile(
    r"https://discord\.com/channels/(?P<server>\d+)/(?P<channel>\d+)"
    r"(?:/(?P<message>\d+))?/?(?:\?.*)?"
)


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def format_time(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def main() -> None:
    if len(sys.argv) != 2:
        fail(f"Usage: {Path(sys.argv[0]).name} <discord-channel-or-message-url>")

    if not os.environ.get("DISCORD_TOKEN"):
        fail("DISCORD_TOKEN is not set")

    match = URL_PATTERN.fullmatch(sys.argv[1])
    if match is None:
        fail("Expected https://discord.com/channels/<server>/<channel>[/<message>]")

    channel_id = match.group("channel")
    message_id = match.group("message")
    before = datetime.now(UTC)
    suffix = "latest"

    if message_id:
        timestamp_ms = (int(message_id) >> 22) + DISCORD_EPOCH_MS
        before = datetime.fromtimestamp(timestamp_ms / 1000, UTC) + timedelta(seconds=1)
        suffix = message_id

    after = before - timedelta(days=7)
    output = Path("/tmp/opencode") / f"discord-{channel_id}-{suffix}.txt"

    subprocess.run(
        [
            "mise",
            "exec",
            "--",
            "DiscordChatExporter.Cli",
            "export",
            "--channel",
            channel_id,
            "--format",
            "PlainText",
            "--output",
            str(output),
            "--after",
            format_time(after),
            "--before",
            format_time(before),
            "--utc",
        ],
        check=True,
    )
    print(output)


if __name__ == "__main__":
    main()
