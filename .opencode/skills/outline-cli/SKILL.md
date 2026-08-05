---
name: outline-cli
description: >-
  Use when searching, reading, creating, updating, moving, archiving, or deleting Outline wiki
  documents and collections via the `ol` CLI (`@doist/outline-cli`, installed via mise); managing
  the household knowledge base at `wiki.${SECRET_DOMAIN}`; scripting bulk document operations
  with `--json`/`--ndjson`; authenticating or updating the CLI. Triggers on phrases like "search
  the wiki", "create an Outline doc", "update the Outline page", "list collections", "move this
  doc", or any invocation of the `ol` command. Do NOT use for content that belongs in the repo
  `docs/` directory (ADRs, investigations, runbooks, AGENTS.md directives) per the Outline vs
  docs/ boundary.
---

# Outline CLI (ol)

Use this skill when the user wants to interact with their Outline wiki/knowledge base.

Run `ol --help` and the relevant subcommand's `--help` for current syntax. Use `--json` for bounded
structured results and `--ndjson` for streaming bulk operations.

## Workflow

1. Search narrowly and resolve the document or collection from structured output.
2. Read the current document before updating, moving, archiving, or deleting it.
3. Confirm the target ID, title, collection, and parent before a destructive operation.
4. Perform the requested operation.
5. Re-read the result and verify its title, content, collection, parent, and publication state.

Document references may be a URL ID, full Outline URL, or document ID. Do not guess when a search
returns multiple matches.

If authentication or network access fails, stop and report the failure. Do not replace `ol` with
raw HTTP requests.
