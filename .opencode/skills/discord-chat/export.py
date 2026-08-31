#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

import argparse
import os
import re
import subprocess
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


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--after", type=parse_time)
    parser.add_argument("--before", type=parse_time)
    args = parser.parse_args()

    if (args.after is None) != (args.before is None):
        fail("--after and --before must be specified together")
    if args.after and args.after >= args.before:
        fail("--after must be earlier than --before")

    if not os.environ.get("DISCORD_TOKEN"):
        fail("DISCORD_TOKEN is not set")

    match = URL_PATTERN.fullmatch(args.url)
    if match is None:
        fail("Expected https://discord.com/channels/<server>/<channel>[/<message>]")

    channel_id = match.group("channel")
    message_id = match.group("message")
    before = datetime.now(UTC)
    suffix = "latest"

    if message_id:
        if args.after:
            fail("explicit ranges require a channel URL")
        timestamp_ms = (int(message_id) >> 22) + DISCORD_EPOCH_MS
        before = datetime.fromtimestamp(timestamp_ms / 1000, UTC) + timedelta(seconds=1)
        suffix = message_id

    if args.after:
        after = args.after
        before = args.before
        suffix = f"{after:%Y%m%d}-{before:%Y%m%d}"
    else:
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
