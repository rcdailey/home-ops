---
name: home-assistant
description: >-
  Use when querying or mutating Home Assistant via `./scripts/hass.py` (entity states, attributes,
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
(`./scripts/hass.py`). The tool is organized as a package at `scripts/hass/` with one module per
subcommand.

## Continuous Improvement (mandatory)

`hass.py` and this skill are perpetual WIP. When using the tool, you MUST fix problems and improve
usability in real time as you observe them: change CLI interfaces, refactor internals, add error
handling, restructure subcommands. Refactor mercilessly. If something is awkward, broken, or could
be better, fix it now rather than working around it. Replaced flags or subcommands should be removed
outright (no dual-support); update this doc in the same pass.

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

`./scripts/hass.py` requires `SECRET_DOMAIN` and `HASS_TOKEN` environment variables (sourced from
`.mise.local.toml`). Run `./scripts/hass.py --help` for the full command list; each subcommand has
its own `--help`.

### Subcommands

**states** -- list entities with built-in projection and limiting:

```bash
hass.py states                                # Domain summary (count per domain)
hass.py states light                          # List lights (default limit: 20)
hass.py states light -n 5                     # List 5 lights
hass.py states light --all                    # No limit (use sparingly)
hass.py states sensor.temperature             # Single entity full detail
hass.py states sensor.temp light.office       # Multiple entities (full entity_ids only)
```

**template** -- render Jinja2 (handles JSON quoting internally):

```bash
hass.py template '{{ states("sensor.temperature") }}'
hass.py template '{{ state_attr("remote.nz7", "content_type") }}'
```

**config** -- get automation/script configuration:

```bash
hass.py config automation automation.my_automation    # By entity_id
hass.py config automation 85a1b949-...                # By UUID
hass.py config script script.my_script                # By entity_id
hass.py config script my_script                       # By slug
```

Accepts entity_id, UUID (automation), or slug (script). Script entity_ids are resolved to slugs via
the entity registry when they diverge from the `entity_id` suffix.

**attributes** -- show entity attributes only:

```bash
hass.py attributes remote.harmony_media_room
```

**orient** -- discover all entities, automations, scripts, and dashboard cards for a topic:

```bash
hass.py orient jvc nz7 harmony        # JVC projector system
hass.py orient "media room"            # Media room devices
```

Run this first when starting any HA topic.

**trigger** -- fire an automation or run a script:

```bash
hass.py trigger automation.my_automation
hass.py trigger script.set_mode --vars '{"hdr_mode": "user_4"}'
```

**entity** -- enable/disable entities in the registry:

```bash
hass.py entity enable sensor.jvc_projector_hdr_mode
hass.py entity disable sensor.some_entity
```

**logs** -- parsed and filtered HA error log:

```bash
hass.py logs                              # Warnings+ (last 50)
hass.py logs -l ERROR                     # Errors+ only
hass.py logs jvc                          # Grep for "jvc" (case-insensitive)
hass.py logs -l DEBUG -n 100              # Last 100 debug+ entries
```

Severity filter plus optional regex grep. Tracebacks stay attached to their parent entry.

**history** -- entity state history with statistics:

```bash
hass.py history sensor.temperature             # Last 24h (default), head/tail
hass.py history sensor.x sensor.y --from 48    # Multiple entities, 48h back
hass.py history sensor.x --from 2h --summary   # Summary (numeric or categorical)
hass.py history sensor.x --from 2026-04-01T00:00:00 --to 2026-04-02T00:00:00
hass.py history sensor.x --from 24 --json      # Raw JSON output
```

`--from` accepts hours (number or `Nh`) or ISO timestamps. `--summary` picks the shape per entity:
numeric sensors get min/max/first/last/resets; string/enum entities get unique-value counts plus a
deduplicated transition timeline.

**activity** -- entity logbook timeline:

```bash
hass.py activity sensor.total_power           # Last 1 hour
hass.py activity light.office --hours 24
```

**area** -- manage areas and entity area assignments:

```bash
hass.py area list
hass.py area get sensor.ct10_power_server
hass.py area set sensor.ct10_power_server server_room
hass.py area set "sensor.a,sensor.b" "Media Room"     # Batch (comma-separated)
hass.py area create "Upstairs"
```

Area resolution accepts area_id or display name (case-insensitive). Entity-level area overrides the
device-inherited area.

**energy** -- energy dashboard configuration:

```bash
hass.py energy                                        # Show current config
hass.py energy get --json
hass.py energy validate                               # Check for broken references
hass.py energy device add sensor.x_daily_energy
hass.py energy device remove sensor.x_daily_energy
hass.py energy device replace sensor.old sensor.new
```

`device` mutations are read-modify-write; `validate` reports broken entity references.

**dashboard** -- inspect Lovelace dashboards and cards:

```bash
hass.py dashboard list                         # All dashboards
hass.py dashboard get [url_path]               # Full config
hass.py dashboard cards [url_path] --type bubble-card
hass.py dashboard resources                    # JS/CSS resources
```

**repairs** -- list and dismiss HA repair issues:

```bash
hass.py repairs                                       # List active
hass.py repairs dismiss deprecated_sensor             # Substring match
hass.py repairs dismiss jvc_projector/full_issue_id   # domain/id
```

**raw** -- direct API calls for endpoints without a subcommand:

```bash
hass.py raw GET /api/services
hass.py raw POST /api/services/light/turn_on '{"entity_id":"light.office"}'
echo '{"entity_id":"light.office"}' | hass.py raw POST /api/services/light/turn_on -
```

## Updating Automations and Scripts

Edits go through JSON via the config API (HA stores YAML internally but exposes JSON). Workflow:

1. Read current config: `hass.py config automation <entity_id> > /tmp/orig.json`
2. Modify with `jq` into a new file
3. Diff original vs modified to verify only intended changes
4. POST via stdin: `cat /tmp/fixed.json | hass.py raw POST /api/config/automation/config/<uuid> -`
5. Re-read the config to confirm

The POST replaces the entire config; the payload must be the complete object.

## Writing Automations From Scratch

When authoring a new automation or script YAML (not mutating an existing JSON config), use Context7
for trigger/condition/action syntax rather than this skill. Query:
`/home-assistant/home-assistant.io`.

## Endpoints Without a Subcommand

For `raw` calls, these endpoints have no dedicated subcommand:

- `POST /api/states/<entity_id>` + `{"state": ..., "attributes": {...}}` -- set entity state
- `POST /api/events/<event_type>` + `{...}` -- fire an event
- `POST /api/config/core/check_config` (no body) -- validate HA config
- `GET /api/services` -- full service registry (pipe to `jq` to inspect service schemas)
- `GET /api/events` -- event types with listener counts

All other common endpoints are covered by subcommands.
