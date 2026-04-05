# JVC projector picture mode automation broken after integration upgrade

- **Date:** 2026-03-28
- **Status:** RESOLVED

## Summary

The JVC NZ7 projector picture mode automation stopped working after the core `jvc_projector`
integration was rewritten in HA 2026.3. The automation and script referenced attributes and command
formats from the old HACS integration that no longer exist. We fixed entity references and value
formats, but the `remote.send_command` approach for setting picture mode is fundamentally
incompatible with the 2.0 integration. A `select.nz7_picture_mode` entity is coming in HA 2026.4
that will resolve this.

## Symptoms

- Picture mode not switching when changing Harmony activities (PS4, Shield)
- No visible errors in the HA UI (script calls failed silently because the referenced script entity
  didn't exist)
- Two JVC devices showing in HA: one from the dead HACS integration, one from core

## Investigation

### Recon

Queried all `nz7`/`jvc`/`harmony` entities via `hass-api.py orient`. Found the automation
(`automation.jvc_hdr_pm_automation`) and script (`script.jvc_set_expected_picture_mode`).

The automation triggers on content type changes, Harmony activity changes, and HA restart. It passes
HDR/SDR picture mode values to the script based on the current Harmony activity:

- Gaming (PS4, Nintendo Switch): HDR `user-4`, SDR `user-1`
- Streaming (Shield): HDR `frame-adapt-hdr`, SDR `natural`

### Entity reference mismatch

The automation called `script.jvc_set_expected_picture_mode` but the actual entity was
`script.set_expected_picture_modes`. Fixed via `POST /api/config/automation/config/<uuid>`.

Then discovered that script entity_ids and service names differ. The entity is
`script.set_expected_picture_modes` but the service is `script.jvc_set_expected_picture_mode` (the
config slug). The automation needs the service name.

### Dead attributes on remote.nz7

The script checked `state_attr('remote.nz7', 'content_type')` and `state_attr('remote.nz7',
'picture_mode')`. Both returned `None`.

Cloned the HACS integration repo (`iloveicedgreentea/jvc_homeassistant`) and found that
`extra_state_attributes` was never defined on the remote entity in this version. Those attributes
were moved to dedicated sensor entities:

- `content_type` -> `sensor.jvc_projector_hdr_mode` (disabled by default)
- `picture_mode` -> `sensor.nz7_picture_mode`

### Stale HACS integration conflict

The HACS integration (`iloveicedgreentea/jvc_homeassistant`) was abandoned. The author's code was
merged into HA core by SteveEasley in HA 2026.3 ([AVS Forum thread][avs-thread]).

After removing the HACS integration, adding the core integration failed with:

```txt
Error occurred loading flow for integration jvc_projector:
cannot import name 'JvcProjector' from 'jvcprojector'
(/config/.venv/lib/python3.14/site-packages/jvcprojector/__init__.py)
```

The old HACS integration's Python package (`pyjvcprojector_test-1.1.7`) installed to the
`jvcprojector` namespace, colliding with the core integration's `pyjvcprojector==2.0.3`. Python
loaded the stale `.venv` copy first. This was the exact collision described in [AVS Forum post
\#200][avs-200].

Fixed by removing stale packages from `/config/.venv/`:

```bash
kubectl exec -n home deploy/home-assistant -- rm -rf \
  /config/.venv/lib/python3.14/site-packages/jvcprojector \
  /config/.venv/lib/python3.14/site-packages/pyjvcprojector_test-1.1.7.dist-info
```

### Value format changes

The 2.0 integration changed picture mode value formats (e.g., `user4` -> `user-4`, `frame_adapt_hdr`
-> `frame-adapt-hdr`). Updated both automation and script configs.

### Enabled HDR sensor

`sensor.jvc_projector_hdr_mode` was disabled by default. Enabled it via WebSocket API
(`config/entity_registry/update`). Reports values: `sdr`, `hdr`, `smpte-st-2084`, `hybrid-log`,
`hdr10p`.

### Updated automation and script

Rewrote the script to check `states('sensor.jvc_projector_hdr_mode')` and
`states('sensor.nz7_picture_mode')` instead of the dead remote attributes. Updated the automation
triggers to fire on `sensor.jvc_projector_hdr_mode` state changes.

### remote.send_command broken in 2.0

The script uses `remote.send_command` with `picture_mode,<value>` to set the picture mode. The 2.0
integration only accepts remote button names (menu, ok, back, etc.) and rejects `command,value`
pairs:

```txt
Error for call_service at pos 1: picture-mode,frame-adapt-hdr is not a known command
```

Confirmed by reading the 2.0 `remote.py` source: commands are validated against a fixed list and
underscores are converted to hyphens, so `picture_mode,frame-adapt-hdr` becomes
`picture-mode,frame-adapt-hdr` which isn't in the list.

The 2.0 integration expects picture mode to be set via a `select` entity, but
`select.nz7_picture_mode` was added in [PR #165194][pr-select] (March 18, 2026) and isn't in HA
2026.3.4.

## Root Cause

Three separate issues:

1. The HACS integration left behind a stale Python package that shadowed the core integration's
   library, preventing the config flow from loading.

2. The automation and script referenced attributes (`content_type`, `picture_mode`) on `remote.nz7`
   that the 2.0 integration moved to dedicated sensor entities, and used value formats (`user4`)
   that changed to hyphenated form (`user-4`).

3. The 2.0 integration removed support for `command,value` pairs in `remote.send_command`, replacing
   that functionality with `select` entities that aren't available until HA 2026.4.

## Resolution

**Fixed:**

- Removed stale `pyjvcprojector_test` package from `/config/.venv/`
- Removed dead HACS integration, confirmed core integration working
- Enabled `sensor.jvc_projector_hdr_mode` (disabled by default)
- Updated automation triggers to use `sensor.jvc_projector_hdr_mode`
- Updated script to check sensor entities instead of remote attributes
- Updated all picture mode values to hyphenated format
- Fixed script service name reference (`script.jvc_set_expected_picture_mode`)

**Completed (HA 2026.4.1, April 4):**

- Enabled `select.nz7_picture_mode` (disabled by integration by default)
- Rewrote script to use `select.select_option` instead of `remote.send_command`
- Updated condition checks to compare against `select.nz7_picture_mode` state (guarantees format
  consistency with the option values)
- Updated automation picture mode values from hyphenated (`user-4`, `frame-adapt-hdr`) to
  underscored (`user_4`, `frame_adapt_hdr`) to match the select entity's option format

Note: the `select` entity uses underscored values (`user_4`, `frame_adapt_hdr`) while the old
`remote.send_command` path used hyphenated values (`user-4`, `frame-adapt-hdr`). The `sensor`
entity's format is unverified (projector was off during the fix), so comparing against the `select`
entity state avoids any format mismatch risk.

### Tooling built during this investigation

- `scripts/hass-api.py`: Python CLI for HA REST/WebSocket API with subcommands: `states`,
  `template`, `config`, `attributes`, `entity`, `orient`, `activity`, `raw`
- `.opencode/skills/home-assistant/SKILL.md`: on-demand skill for AI-assisted HA work
- `scripts/hass-api.sh`: original bash version, kept for reference

## References

- [AVS Forum: JVC Projectors Home Assistant Integration thread][avs-thread]
- [AVS Forum post #200: Python package collision explained][avs-200]
- [PR #165194: Move jvc_projector sensor entities to select domain][pr-select]
- [PR #160739: Bump pyjvcprojector to 2.0.0][pr-2.0]
- [iloveicedgreentea/jvc_homeassistant (abandoned HACS integration)][hacs-old]
- [SteveEasley/homeassistant_jvc_projector (2.0 HACS beta)][hacs-new]

[avs-thread]:
    https://www.avsforum.com/threads/jvc-projectors-home-assistant-integration-official-thread.3252498/
[avs-200]:
    https://www.avsforum.com/threads/jvc-projectors-home-assistant-integration-official-thread.3252498/post-63818544
[pr-select]: https://github.com/home-assistant/core/pull/165194
[pr-2.0]: https://github.com/home-assistant/core/pull/160739
[hacs-old]: https://github.com/iloveicedgreentea/jvc_homeassistant
[hacs-new]: https://github.com/SteveEasley/homeassistant_jvc_projector
