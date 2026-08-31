---
name: discord-chat
description: >-
  Use when the user provides a discord.com/channels/<server>/<channel> link or a Discord message
  link and asks to inspect, fetch, search, summarize, or use the linked conversation. Do NOT use
  for Discord application, bot, webhook, or server administration.
---

# Discord chat retrieval

Export the week preceding the referenced point to a local plain-text file. Search and read that
file instead of repeatedly calling Discord or loading the entire conversation into context.

## Required input

Accept either URL shape:

- Channel: `https://discord.com/channels/<server-id>/<channel-id>`
- Message: `https://discord.com/channels/<server-id>/<channel-id>/<message-id>`

`DISCORD_TOKEN` must already be present in the environment. Never print, read, or pass it on the
command line.

## Export

Run exactly one command, substituting the URL verbatim:

```sh
.opencode/skills/discord-chat/export.py '<discord-url>'
```

Example for a channel link:

```sh
.opencode/skills/discord-chat/export.py \
  'https://discord.com/channels/673534664354430999/1097927240978808882'
```

Example for a message link:

```sh
.opencode/skills/discord-chat/export.py \
  'https://discord.com/channels/673534664354430999/1097927240978808882/1543962458941685761'
```

The command invokes `DiscordChatExporter.Cli` through mise and writes the export under
`/tmp/opencode`:

- Channel link: seven days ending when the command starts
- Message link: seven days preceding the linked message, including that message
- Format: plain text, without media downloads
- Filename: `discord-<channel-id>-latest.txt` or
  `discord-<channel-id>-<message-id>.txt`

## Use the export

The command prints the output path after a successful export. Reuse that file for all subsequent
searches and reads in the task. Use Grep to locate names, dates, errors, or topics, then Read only
the relevant ranges. Do not rerun the export or read the whole file unless the user requests newer
messages or the available context is insufficient.

The exporter renders timestamps in UTC. A message-link export ends one second after the target's
timestamp, so start near the end of the file when the linked message is the focus.

## Failure behavior

- Missing `DISCORD_TOKEN`: stop and ask the user to expose it to the current environment.
- Invalid URL: report the accepted URL shapes above.
- Discord permission or authentication error: report it without exposing the token.
- Empty export: verify that the account can view the channel; do not broaden the date range unless
  the user asks or the task requires older context.
