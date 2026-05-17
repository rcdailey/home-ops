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

## Continuous Improvement (mandatory)

`hass.sh` and this skill are perpetual WIP. When using the tool, you MUST fix problems and improve
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

`./scripts/hass.sh` requires `SECRET_DOMAIN` and `HASS_TOKEN` environment variables (sourced from
`.mise.local.toml`). Run `./scripts/hass.sh --help` for the full command list; each subcommand has
its own `--help`.

### Subcommands

**states** -- list entities with built-in projection and limiting:

```bash
hass.sh states                                # Domain summary (count per domain)
hass.sh states light                          # List lights (default limit: 20)
hass.sh states light -n 5                     # List 5 lights
hass.sh states light --all                    # No limit (use sparingly)
hass.sh states sensor.temperature             # Single entity full detail
hass.sh states sensor.temp light.office       # Multiple entities (full entity_ids only)
```

**template** -- render Jinja2 (handles JSON quoting internally):

```bash
hass.sh template '{{ states("sensor.temperature") }}'
hass.sh template '{{ state_attr("remote.nz7", "content_type") }}'
```

**config** -- get automation/script configuration:

```bash
hass.sh config automation automation.my_automation    # By entity_id
hass.sh config automation 85a1b949-...                # By UUID
hass.sh config script script.my_script                # By entity_id
hass.sh config script my_script                       # By slug
```

Accepts entity_id, UUID (automation), or slug (script). Script entity_ids are resolved to slugs via
the entity registry when they diverge from the `entity_id` suffix.

**attributes** -- show entity attributes only:

```bash
hass.sh attributes remote.harmony_media_room
```

**orient** -- discover all entities, automations, scripts, and dashboard cards for a topic:

```bash
hass.sh orient jvc nz7 harmony        # JVC projector system
hass.sh orient "media room"            # Media room devices
```

Run this first when starting any HA topic.

**trigger** -- fire an automation or run a script:

```bash
hass.sh trigger automation.my_automation
hass.sh trigger script.set_mode --vars '{"hdr_mode": "user_4"}'
```

**entity** -- enable/disable entities in the registry:

```bash
hass.sh entity enable sensor.jvc_projector_hdr_mode
hass.sh entity disable sensor.some_entity
```

**logs** -- parsed and filtered HA error log:

```bash
hass.sh logs                              # Warnings+ (last 50)
hass.sh logs -l ERROR                     # Errors+ only
hass.sh logs jvc                          # Grep for "jvc" (case-insensitive)
hass.sh logs -l DEBUG -n 100              # Last 100 debug+ entries
hass.sh logs --full                       # Disable duplicate squashing
```

Severity filter plus optional regex grep. Tracebacks stay attached to their parent entry. By
default, entries with identical bodies (recurring tracebacks from flapping integrations) are
squashed to one line with occurrence count and `first..last` timestamp range, collapsing the
traceback to `headline | final exception line`. Pass `--full` to print every entry verbatim.

**history** -- entity state history with statistics:

```bash
hass.sh history sensor.temperature             # Last 24h (default), head/tail
hass.sh history sensor.x sensor.y --from 48    # Multiple entities, 48h back
hass.sh history sensor.x --from 2h --summary   # Summary (numeric or categorical)
hass.sh history sensor.x --from 2026-04-01T00:00:00 --to 2026-04-02T00:00:00
hass.sh history sensor.x --from 24 --json      # Raw JSON output
```

`--from` accepts hours (number or `Nh`) or ISO timestamps. `--summary` picks the shape per entity:
numeric sensors get min/max/first/last/resets; string/enum entities get unique-value counts plus a
deduplicated transition timeline.

**activity** -- entity logbook timeline:

```bash
hass.sh activity sensor.total_power           # Last 1 hour
hass.sh activity light.office --hours 24
```

**area** -- manage areas and entity area assignments:

```bash
hass.sh area list
hass.sh area get sensor.ct10_power_server
hass.sh area set sensor.ct10_power_server server_room
hass.sh area set "sensor.a,sensor.b" "Media Room"     # Batch (comma-separated)
hass.sh area create "Upstairs"
```

Area resolution accepts area_id or display name (case-insensitive). Entity-level area overrides the
device-inherited area.

**energy** -- energy dashboard configuration:

```bash
hass.sh energy                                        # Show current config
hass.sh energy get --json
hass.sh energy validate                               # Check for broken references
hass.sh energy device add sensor.x_daily_energy
hass.sh energy device remove sensor.x_daily_energy
hass.sh energy device replace sensor.old sensor.new
```

`device` mutations are read-modify-write; `validate` reports broken entity references.

**dashboard** -- inspect Lovelace dashboards and cards:

```bash
hass.sh dashboard list                         # All dashboards
hass.sh dashboard get [url_path]               # Full config
hass.sh dashboard cards [url_path] --type bubble-card
hass.sh dashboard resources                    # JS/CSS resources
```

**repairs** -- list and dismiss HA repair issues:

```bash
hass.sh repairs                                       # List active
hass.sh repairs dismiss deprecated_sensor             # Substring match
hass.sh repairs dismiss jvc_projector/full_issue_id   # domain/id
```

**raw** -- direct API calls for endpoints without a subcommand:

```bash
hass.sh raw GET /api/services
hass.sh raw POST /api/services/light/turn_on '{"entity_id":"light.office"}'
echo '{"entity_id":"light.office"}' | hass.sh raw POST /api/services/light/turn_on -
```

## Updating Automations and Scripts

Edits go through JSON via the config API (HA stores YAML internally but exposes JSON). Workflow:

1. Read current config: `hass.sh config automation <entity_id> > /tmp/orig.json`
2. Modify with `jq` into a new file
3. Diff original vs modified to verify only intended changes
4. POST via stdin: `cat /tmp/fixed.json | hass.sh raw POST /api/config/automation/config/<uuid> -`
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
