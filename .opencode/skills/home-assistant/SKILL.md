---
name: home-assistant
description: >-
  Use when querying Home Assistant entity states, calling services, managing automations,
  debugging devices, or authoring automation YAML
---

# Home Assistant API

Interact with a Home Assistant instance via its REST API using a Python CLI tool built on
`homeassistant-api` SDK. No MCP server required.

## Context Efficiency Rules

The HA instance has 1000+ entities and 60+ service domains. Unfiltered API responses will overwhelm
context. These rules are mandatory:

- **NEVER dump full collections.** Subcommands handle projection and limiting automatically. For
  `raw` queries, pipe through `jq` to filter before outputting.
- **Default limit is 20.** The `states` subcommand enforces this. Use `-n` to adjust or `--all` to
  remove (sparingly). For raw queries, apply `| .[:20]` to arrays.
- **Prefer subcommands over raw.** `states`, `attributes`, `config`, `template`, `orient` handle
  projection and formatting automatically. Use `raw` only for endpoints without a subcommand.
- **Use orient first.** When starting work on any HA topic, run `orient` with relevant search terms
  to discover all related entities, automations, and scripts in one call.
- **Write large results to /tmp.** If output exceeds ~100 lines, redirect to `/tmp/ha-*.json` and
  search with rg selectively.

## Tool

`./scripts/hass-api.py` wraps the Home Assistant REST API. Requires `SECRET_DOMAIN` and `HASS_TOKEN`
environment variables (sourced from `.mise.local.toml`). Depends on `homeassistant-api` (pip) and
`aiohttp` (pip, for entity enable/disable only).

### Subcommands

**states** -- list entities with built-in projection and limiting:

```bash
hass-api.py states                        # Domain summary (count per domain)
hass-api.py states light                  # List lights (default limit: 20)
hass-api.py states light -n 5             # List 5 lights
hass-api.py states light --all            # No limit (use sparingly)
hass-api.py states sensor.temperature     # Single entity full detail
```

**template** -- render Jinja2 (handles JSON quoting internally):

```bash
hass-api.py template '{{ states("sensor.temperature") }}'
hass-api.py template '{{ state_attr("remote.nz7", "content_type") }}'
hass-api.py template '{{ is_state("light.office", "on") }}'
```

**config** -- retrieve automation/script configuration:

```bash
hass-api.py config automation automation.my_automation   # By entity_id
hass-api.py config automation 85a1b949-...               # By UUID
hass-api.py config script script.my_script               # By entity_id
hass-api.py config script my_script                      # By slug
```

Automation configs use the UUID from `attributes.id`; the subcommand resolves entity_id to UUID
automatically. Script configs use the object_id slug (entity_id minus `script.` prefix).

**attributes** -- show entity attributes only:

```bash
hass-api.py attributes remote.harmony_media_room
hass-api.py attributes select.nz7_installation_mode
```

**orient** -- discover all entities, automations, and scripts related to a topic:

```bash
hass-api.py orient jvc nz7 harmony        # JVC projector system
hass-api.py orient pool                    # Pool equipment
hass-api.py orient "media room"            # Media room devices
```

Searches entity IDs, friendly names, and automation/script configs for matching terms. Outputs
matching entities with current state, then full configs for related automations and scripts. Use
this first when starting work on any HA topic.

**entity** -- enable/disable entities via WebSocket API (requires `aiohttp`):

```bash
hass-api.py entity enable sensor.jvc_projector_hdr_mode
hass-api.py entity disable sensor.some_entity
```

**raw** -- direct API calls for everything else:

```bash
hass-api.py raw GET /api/services
hass-api.py raw POST /api/services/light/turn_on '{"entity_id":"light.office"}'
echo '{"entity_id":"light.office"}' | hass-api.py raw POST /api/services/light/turn_on -
```

Body can be a JSON string, `-` for stdin, or omitted.

## REST API Reference

Endpoints available via `raw` (subcommands cover the common ones above):

### Read

- `GET /api/` -- connectivity check
- `GET /api/config` -- instance config (version, location, timezone, components)
- `GET /api/states` -- all entity states (LARGE: use `states` subcommand instead)
- `GET /api/states/<entity_id>` -- single entity (use `states <entity_id>` instead)
- `GET /api/services` -- all service domains with field schemas (LARGE)
- `GET /api/events` -- event types with listener counts
- `GET /api/history/period/<timestamp>` -- state history
- `GET /api/logbook/<timestamp>` -- logbook entries
- `GET /api/error_log` -- plain text error log
- `GET /api/config/automation/config/<uuid>` -- automation config (use `config` instead)
- `GET /api/config/script/config/<slug>` -- script config (use `config` instead)

### Write

- `POST /api/services/<domain>/<service>` + `{"entity_id": "..."}` -- call a service
- `POST /api/states/<entity_id>` + `{"state": "...", "attributes": {...}}` -- set entity state
- `POST /api/events/<event_type>` + `{"key": "value"}` -- fire an event
- `POST /api/template` + `{"template": "{{ ... }}"}` -- render template (use `template` instead)
- `POST /api/config/core/check_config` -- validate configuration (no body)
- `POST /api/config/automation/config/<uuid>` + full config JSON -- update automation
- `POST /api/config/script/config/<slug>` + full config JSON -- update script

### Updating Automations and Scripts

The config endpoints accept POST to update existing configs. Workflow:

1. Read current config: `hass-api.py config automation <entity_id>` and redirect to /tmp
2. Modify with `jq` and write to a new file
3. Diff original vs modified to verify only intended changes
4. POST via stdin: `cat /tmp/fixed.json | hass-api.py raw POST /api/config/automation/config/<uuid>
   -`
5. Re-read the config to confirm the change persisted

The POST replaces the entire config; the payload must be the complete object.

### Script Service Names

Script entity_ids and service names differ. The service name uses the config slug (the key under
which the script is stored), not the entity_id. Check `GET /api/services` filtered to `script`
domain to find the correct service name. Example: entity `script.set_expected_picture_modes` has
service `script.jvc_set_expected_picture_mode`.

### Query Parameters (history)

- `?filter_entity_id=sensor.x,sensor.y&minimal_response&no_attributes`
- Add `&end_time=<ISO>` to bound history queries; unbounded queries are expensive.

## Common Raw Patterns

For operations without dedicated subcommands:

```bash
# Service call
hass-api.py raw POST /api/services/light/turn_on \
  '{"entity_id": "light.living_room", "brightness": 128}'

# Service field schema (what arguments does a service accept?)
hass-api.py raw GET /api/services \
  | jq '.[] | select(.domain == "light") | .services.turn_on'

# Recent history (single entity, minimal)
hass-api.py raw GET \
  "/api/history/period?filter_entity_id=sensor.temp&minimal_response&no_attributes"

# Find entities matching a pattern across domains
hass-api.py raw GET /api/states \
  | jq '[.[] | select(.entity_id | test("jvc|projector"; "i"))
    | {entity_id, state, name: .attributes.friendly_name}]'
```

## Automation YAML Authoring

Automations are authored as YAML and applied through the HA UI or API. Core structure:

```yaml
alias: Descriptive Name
description: What this automation does and why
mode: single  # single | restart | queued | parallel

triggers:
  - trigger: state
    entity_id: binary_sensor.motion
    to: "on"

conditions:
  - condition: time
    after: "18:00:00"
    before: "06:00:00"

actions:
  - action: light.turn_on
    target:
      entity_id: light.hallway
    data:
      brightness_pct: 80
```

### Trigger types

`state`, `numeric_state` (above/below), `time`, `time_pattern`, `sun` (sunrise/sunset with offset),
`zone` (enter/leave), `device`, `mqtt`, `webhook`, `event`, `template`, `calendar`.

### Condition types

`state`, `numeric_state`, `time`, `sun`, `zone`, `template`, `and`, `or`, `not`.

### Action types

`action` (service call), `delay`, `wait_template`, `wait_for_trigger`, `choose`, `if/then/else`,
`repeat`, `event`, `variables`, `stop`, `parallel`.

### Tips

- `mode: restart` is useful for motion-based automations (re-triggers reset the delay).
- Use `choose` for branching logic instead of multiple automations.
- `variables` at the top of actions lets you define reusable values.
- Templating uses Jinja2: `{{ states('sensor.temperature') | float > 80 }}`.

## Documentation Lookup

For API details beyond this quick reference, use Context7. Call `query-docs` directly; do NOT call
`resolve-library-id` first.

- API/developer docs: `/home-assistant/developers.home-assistant` (3500+ snippets)
- Integration-specific docs (ZHA, MQTT, climate): `/home-assistant/home-assistant.io`

## Diagnostics

When debugging entity or automation issues:

1. Check entity state: `hass-api.py states <entity_id>`
2. Check attributes: `hass-api.py attributes <entity_id>`
3. Get automation/script config: `hass-api.py config automation|script <id>`
4. Render templates to test conditions: `hass-api.py template '<jinja2>'`
5. Check error log: `hass-api.py raw GET /api/error_log` (returns plain text; write to /tmp and
   search with rg for relevant keywords)
6. Check service fields: `hass-api.py raw GET /api/services | jq '.[] | select(.domain == "X")'`
7. Check history: `hass-api.py raw GET "/api/history/period?filter_entity_id=X&minimal_response"`
