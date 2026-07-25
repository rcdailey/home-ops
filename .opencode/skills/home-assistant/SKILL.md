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
the entity registry when they diverge from the `entity_id` suffix. Read-only; use `edit` to change a
config.

**edit** -- pull an automation, script, or dashboard view to a YAML file, edit it, push it back:

```bash
hass.sh edit pull automation automation.pool_feature_activator   # -> ~/.cache/hass/edit/*.yaml
hass.sh edit pull script script.vacuum_toggle -o /tmp/vac.yaml
hass.sh edit pull view lovelace --view Pool -o /tmp/pool.yaml
hass.sh edit push /tmp/pool.yaml --dry-run                       # diff only
hass.sh edit push /tmp/pool.yaml
hass.sh edit create automation 1753500000000 -f /tmp/new.yaml
hass.sh edit delete automation automation.old_thing
```

This replaces hand-rolled `jq` surgery plus `raw POST`. Workflow: `pull`, edit the file body with
ordinary text edits, `push`.

`pull` writes a self-describing file: a `# hass-edit-*` comment header naming the object and the
digest of its upstream config at pull time, followed by the config as YAML. `push` needs only the
path. The header is read from anywhere in the file, so the body can be rewritten freely (even
replaced with JSON), but it must survive; a file without it fails with a re-pull instruction rather
than writing anything.

`push` refuses when the upstream object changed after the pull, printing the drift diff; re-pull and
reapply, or repeat with `--force`. It prints a unified diff of what it will change, and when the
file matches upstream it reports `no changes` and writes nothing. After a write it re-reads the
stored object and prints a `note: HA rewrote the stored config` diff if HA normalized anything.

Round-trip fidelity verified on this instance (HA 2026.7.4): pull-then-push-unchanged is a true
no-op, and a pushed config comes back byte-identical (key order, `triggers`/`actions` naming, empty
`description`, and `data: {}` all preserved). The only rewrite observed is on `create`, where HA
injects the `id` field matching the REF you created under.

`create` takes the new automation UUID or script slug as REF plus a plain config file (no header);
it refuses if the object already exists. `delete` takes an entity_id, UUID, or slug. Config
validation errors come back as HA's own text, e.g.
`error: HTTP 400: Message malformed: Invalid trigger 'bogus' specified`.

Dashboard views are addressed by the same selectors as `dashboard get` and are pushed by splicing
the view back into the dashboard config, so other views are untouched. An unresolvable `--view`
fails with the candidate list. Views cannot be created or deleted this way; use `dashboard`.

**attributes** -- show entity attributes only:

```bash
hass.sh attributes remote.harmony_media_room
```

**services** -- list available HA services:

```bash
hass.sh services                              # Domain summary (count per domain)
hass.sh services notify                       # List services in domain
hass.sh services notify.mobile_app_pixel_8_pro  # Service fields/schema
```

**orient** -- discover all entities, automations, scripts, and dashboard cards for a topic:

```bash
hass.sh orient jvc nz7 harmony        # JVC projector system
hass.sh orient "media room"            # Media room devices
```

Run this first when starting any HA topic.

**call** -- invoke any service action:

```bash
hass.sh call media_player.volume_set media_player.wiim_patio --data 'volume_level: 0.2'
hass.sh call light.turn_on light.office light.desk --data '{"brightness_pct": 40}'
hass.sh call homeassistant.check_config                       # No target entity
hass.sh call weather.get_forecasts weather.home --data 'type: daily' --response
```

Positional arguments after the service are target entity_ids (omit for services that take no
target). `--data` takes YAML or JSON (`-` reads stdin) for the remaining service fields.

Calls go over the WebSocket API, so a failure prints HA's own reason and exits 1, e.g.
`error: ServiceNotSupported: Entity media_player.wiim_patio does not support action
media_player.join`. Never call services through `raw POST /api/services/...`: that endpoint answers
every failure with a bare 500 and no detail.

`--response` requests service response data (`weather.get_forecasts`, `calendar.get_events`, ...);
HA rejects it for services that return nothing.

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

**dashboard** -- inspect and edit Lovelace dashboards:

```bash
hass.sh dashboard list                                    # All dashboards
hass.sh dashboard views lovelace                          # Views/sections + selectors
hass.sh dashboard get lovelace --view Pool                # One view as YAML
hass.sh dashboard get lovelace --view Pool --section Maintenance --json
hass.sh dashboard cards lovelace --view Pool --type bubble-card
hass.sh dashboard resources                               # JS/CSS resources
```

`url_path` is optional everywhere (omit for Overview). `get` prints YAML by default (`--json` for
JSON) and multi-line strings render as literal blocks, so its output can be edited and fed straight
back to `card add`. Always narrow with `--view` (and `--section`) instead of dumping a whole
dashboard; a full config runs tens of KB. Run `dashboard views` first to learn the selectors: views
match by title, `path`, or `#index`; sections match by title (a leading `heading` card counts) or
`#index`. Matching is case-insensitive, exact first, then substring; ambiguous or unknown selectors
fail with the list of candidates.

**dashboard card add** -- insert cards from YAML or JSON:

```bash
hass.sh dashboard card add lovelace --view Pool --section Maintenance -f cards.yaml
hass.sh dashboard card add lovelace --view Pool --new-section Speakers -f cards.yaml --dry-run
cat cards.yaml | hass.sh dashboard card add lovelace --view Pool --section Maintenance -f -
```

The input file holds one card mapping or a list of cards (YAML or JSON; `-f -` reads stdin). Exactly
one of `--section` (existing) or `--new-section TITLE` (creates a grid section with a heading card)
is required. `--position N` inserts at an index instead of appending. Every `entity`/`entities`
reference in the incoming cards is checked against live states plus the entity registry, and the
write is refused if any is unknown (Jinja templates are skipped). Always do a `--dry-run` pass first.
Before a real write the pre-write config is stashed at `~/.cache/hass/lovelace/{dashboard}-{ts}.json`
and the path is printed.

**dashboard card list/edit/remove** -- change a card that is already placed:

```bash
hass.sh dashboard card list lovelace --view Pool --section "Pool Audio"
hass.sh dashboard card edit lovelace --view Pool --section "Pool Audio" \
  --card "Patio Speakers" -f card.yaml --dry-run
hass.sh dashboard card remove lovelace --view Pool --section "Pool Audio" --card "#pool-audio"
```

`card list` prints each card as `#index type [card_type] names...` followed by the exact
`selector:` string to pass to `--card`; copy one rather than guessing. A selector is a card `name`,
`heading`, `title`, `hash`, or `entity`, or `#index` within the section as a last resort. Matching
is case-insensitive, exact first, then substring; ambiguous or unknown selectors fail with the
candidate list.

`edit` replaces the addressed card wholesale with the single card in `-f` (same YAML/JSON rules,
entity validation, and pre-write backup as `card add`), so the workflow is: `dashboard get --view V
--section S` into a file, change the keys, feed the one card back. `--dry-run` prints a unified diff
of the old and new card instead of writing. `remove` deletes the addressed card. Neither needs a
restore-and-re-add cycle.

**dashboard restore** -- roll a dashboard back to a stashed config:

```bash
hass.sh dashboard restore ~/.cache/hass/lovelace/lovelace-20260725T170000.json lovelace --dry-run
hass.sh dashboard restore ~/.cache/hass/lovelace/lovelace-20260725T170000.json lovelace
```

**info** -- instance version, core config, and inventory counts:

```bash
hass.sh info
hass.sh info --json
```

Reports HA version and run state, internal/external URLs, safe/recovery mode, and counts for
components, devices, entities, dashboards, config entries by state, pending discovery flows, and
active repairs. Use it as the first call when the HA version or overall health matters.

**integration** -- triage config entries and discovery flows:

```bash
hass.sh integration list                       # Summary + problem entries only
hass.sh integration list --all                 # Include healthy entries
hass.sh integration list --ignored             # Include ignored entries
hass.sh integration list dlna                  # Domain substring: all matches, ignored included
hass.sh integration discovered                 # Pending discovery flows + duplicate hints
hass.sh integration ignore dlna_dmr/wiim-pool  # Dismiss a discovery flow
```

`list` prints one line per entry with state, `disabled_by`/`reason` when unhealthy, and device and
entity counts from the registries; error states (`setup_retry`, `setup_error`, ...) are grouped
first. Bare `hass.sh integration` is the same as `integration list`.

`discovered` correlates each pending flow against existing config entries and prints
`duplicate of <domain> '<title>' (<state>)` when another integration already covers the same device
(e.g. a generic `dlna_dmr` flow for a speaker already adopted by `wiim`). Those are the flows to
dismiss.

`ignore` takes the `domain/slug` selector printed by `discovered`, a title substring, or a raw flow
id, and calls HA's ignore-flow path; the flow becomes a config entry with `source=ignore`, visible
via `integration list --ignored`. Unknown or ambiguous selectors fail with the pending list.

**repairs** -- list and dismiss HA repair issues:

```bash
hass.sh repairs                                       # List active
hass.sh repairs dismiss deprecated_sensor             # Substring match
hass.sh repairs dismiss jvc_projector/full_issue_id   # domain/id
```

**raw** -- direct API calls for endpoints without a subcommand:

```bash
hass.sh raw GET /api/config
hass.sh raw POST /api/events/my_event '{"payload":1}'
echo '{"state":"on"}' | hass.sh raw POST /api/states/sensor.fake -
```

Failures print `error: HTTP <status>: <body>` and exit 1 rather than raising a library traceback.
Use `hass.sh call` for service actions; `raw POST /api/services/...` cannot report why a call failed.

## Writing Automations From Scratch

When authoring a new automation or script YAML (not mutating an existing JSON config), use Context7
for trigger/condition/action syntax rather than this skill. Query:
`/home-assistant/home-assistant.io`.

## Endpoints Without a Subcommand

For `raw` calls, these endpoints have no dedicated subcommand:

- `POST /api/states/<entity_id>` + `{"state": ..., "attributes": {...}}` -- set entity state
- `POST /api/events/<event_type>` + `{...}` -- fire an event
- `POST /api/config/core/check_config` (no body) -- validate HA config
- `GET /api/events` -- event types with listener counts

All other common endpoints are covered by subcommands.
