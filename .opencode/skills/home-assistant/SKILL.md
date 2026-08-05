---
name: home-assistant
description: >-
  Use when querying or mutating Home Assistant via `./scripts/hass.sh` (entity states, attributes,
  templates, history, logbook, areas, energy dashboard, Lovelace dashboards, automations, scripts,
  repairs, registry entries); authoring, editing, or debugging HA automation/script YAML or Jinja
  templates; inspecting entities, devices, integrations, or areas on the HA instance at
  `home.${SECRET_DOMAIN}`; firing events or calling services. Triggers on phrases like "check HA",
  "Home Assistant entity", "trigger this automation", "what's the state of sensor.X", "run the
  script", "HA template", or any edit under `scripts/hass/`. Do NOT use for unrelated
  smart-home/IoT platforms.
---

# Home Assistant API

Interact with a Home Assistant instance via its REST and WebSocket APIs using a Python CLI tool
(`./scripts/hass.sh`). The tool is organized as a package at `scripts/hass/` with one module per
subcommand.

## Context Efficiency Rules

The HA instance has 1000+ entities and 60+ service domains. Unfiltered API responses will overwhelm
context. These rules are mandatory:

- **NEVER dump full collections.** Subcommands handle projection and limiting automatically. For
  `raw` queries, pipe through `jq` to filter before outputting.
- **Default limit is 20.** The `states` subcommand enforces this. Use `-n` to adjust or `--all` to
  remove (sparingly). For raw queries, apply `| .[:20]` to arrays.
- **Prefer subcommands over raw.** `states`, `attributes`, `config`, `template`, `orient`, `history`
  handle projection and formatting automatically. Use `raw` only for endpoints without a subcommand.
- **Use orient first.** When starting work on any HA topic, run `orient` with relevant search terms
  to discover all related entities, automations, scripts, and dashboard cards in one call.
- **Write large results to /tmp.** If output exceeds ~100 lines, redirect to `/tmp/ha-*.json` and
  search with rg selectively.

## Tool

`./scripts/hass.sh` requires `SECRET_DOMAIN` and `HASS_TOKEN` in the environment. Run
`./scripts/hass.sh --help` and the relevant subcommand's `--help` for current syntax.

## Workflow

1. Run `orient` with focused topic terms. Use `info` first when instance health or version matters.
2. Read the smallest relevant state, configuration, history, or dashboard section.
3. Use a dedicated subcommand instead of `raw` when one exists.
4. Run a dry run before any command that supports it.
5. Perform the mutation, then re-read the affected object and verify the outcome.

## Safe mutations

Use `edit pull` and `edit push` for automations, scripts, and dashboard views. Preserve the
`# hass-edit-*` header because it carries the object identity and upstream digest. If `push` reports
drift, re-pull and reapply the change rather than forcing it by default.

Use `call` for service actions. It uses the WebSocket API and returns the actual Home Assistant
failure reason; raw service POST requests often return an unhelpful HTTP 500.

Always dry-run device renames. A device rename can change entity IDs, but stored references in
dashboards, automations, and scripts are reported rather than rewritten. Update and verify those
references separately.

For dashboards, select a view and section instead of retrieving the full configuration. Copy the
selector printed by list commands rather than guessing. Use the command's backup and dry-run flow
before adding, replacing, removing, or restoring cards.

Use `raw` only for endpoints without a dedicated command. Bound and filter its response before it
enters context.

## Authoring YAML

For new automation or script syntax, consult current official Home Assistant documentation. Use the
CLI to validate and then re-read the stored configuration after creation.
