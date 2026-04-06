# Emporia Vue 3 filter migration

- **Date:** 2026-04-05
- **Status:** IN PROGRESS

## Summary

Migrating the Emporia Vue 3 ESPHome configuration from sliding window moving average filters to the
upstream-recommended two-tier approach (raw power for energy integration, throttled copy sensors for
display). Also fixing area assignments and other issues found during review.

## Pre-migration baseline

Captured 2026-04-05 ~18:22 CDT. These readings come from the current config, which applies
`sliding_window_moving_average` (window 24, send every 12) plus `*pos` to all CT power sensors. The
`total_power` template sensor polls every 10 seconds.

### Whole-house

| Sensor             | Value     |
| ------------------ | --------- |
| Total power        | 5762 W    |
| Total daily energy | 10,247 Wh |
| Phase A power      | 3766 W    |
| Phase B power      | 1980 W    |
| Phase A voltage    | 123.2 V   |
| Phase B voltage    | 120.7 V   |

### Per-circuit power (W) and daily energy (Wh)

| CT  | Circuit        | Power (W) | Daily (Wh) |
| --- | -------------- | --------- | ---------- |
| 01  | Subpanel Black | 1719      | 3368       |
| 02  | Subpanel Red   | 556       | 973        |
| 03  | AC Master      | 2         | 111        |
| 04  | AC Office      | 0         | 896        |
| 05  | AC Upstairs    | 1465      | 238        |
| 06  | Oven           | 0         | 3          |
| 07  | Dryer          | 1         | 4          |
| 08  | Pool Red       | 173       | 1402       |
| 09  | Pool Black     | 163       | 1394       |
| 10  | Server         | 413       | 869        |
| 11  | Ice Maker      | 239       | 408        |
| 12  | Media Fridge   | 47        | 60         |
| 13  | Garage GFI     | 19        | 41         |
| 14  | Media 20a      | 582       | 140        |

### Combined template sensors

| Sensor                 | Value   |
| ---------------------- | ------- |
| Subpanel (CT01 + CT02) | 2276 W  |
| Pool (CT08 + CT09)     | 2796 Wh |

## Post-migration baseline

Captured 2026-04-05 ~19:23 CDT (about 1 hour after flash). New config uses raw internal sensors for
energy integration, copy sensors with `throttle_average: 5s` for display, and `throttle: 60s` on
daily energy sensors.

| Sensor             | Value   |
| ------------------ | ------- |
| Total power        | 4180 W  |
| Total daily energy | 1542 Wh |
| Phase A power      | 2882 W  |
| Phase B power      | 1313 W  |
| Phase A voltage    | 123.4 V |
| Phase B voltage    | 121.3 V |
| Balance power      | 296 W   |
| Balance daily      | 65 Wh   |

| CT  | Circuit        | Power (W) | Daily (Wh) |
| --- | -------------- | --------- | ---------- |
| 01  | Subpanel Black | 1803      | 584        |
| 02  | Subpanel Red   | 562       | 151        |
| 03  | AC Master      | 1         | 0.4        |
| 04  | AC Office      | 0         | 0          |
| 05  | AC Upstairs    | 0         | 122        |
| 06  | Oven           | 0         | 0.1        |
| 07  | Dryer          | 2         | 0.6        |
| 08  | Pool Red       | 174       | 79         |
| 09  | Pool Black     | 163       | 75         |
| 10  | Server         | 470       | 167        |
| 11  | Ice Maker      | 351       | 79         |
| 12  | Media Fridge   | 52        | 17         |
| 13  | Garage GFI     | 18        | 7          |
| 14  | Media 20a      | 191       | 195        |

| Combined sensor        | Value  |
| ---------------------- | ------ |
| Subpanel (CT01 + CT02) | 2393 W |
| Pool (CT08 + CT09)     | 154 Wh |
| Balance power          | 296 W  |
| Balance daily energy   | 65 Wh  |

### Comparison notes

The before/after snapshots were taken at different times (18:22 vs 19:23 CDT) with different load
conditions (AC Upstairs was running during before, mostly off during after). Daily energy values are
not comparable because the "after" snapshot was taken only ~1 hour after the daily counter reset at
flash time; "before" values had a full day of accumulation.

**What we can compare (instantaneous power at similar loads):**

- Phase voltages are stable and consistent (123.2/120.7 vs 123.4/121.3; normal grid fluctuation).
- Circuits at steady-state (Server, Media Fridge, Garage GFI, Dryer idle) show values within
  expected measurement noise: Server 413 vs 470 W (normal variation), Media Fridge 47 vs 52 W,
  Garage GFI 19 vs 18 W.
- The new `balance_power` (296 W) represents unmonitored load (lights, outlets, misc circuits not on
  dedicated CTs). This sensor is new; no before comparison exists.

**What changed structurally:**

- `total_power` now has `device_class: power` and `state_class: measurement` (HA will record
  long-term statistics).
- Phase A voltage now uses `moving_avg` filter (was double-`pos` before; bug fix).
- All daily energy sensors throttled to 60s updates (reduces HA recorder write load).
- Copy sensors use `throttle_average: 5s` instead of `sliding_window_moving_average` (window 24,
  send every 12). Both smooth noisy readings; `throttle_average` is simpler and decoupled from the
  raw sensor used for energy integration.

## Issues found during review

1. **`total_power` missing metadata.** The ESPHome template sensor does not set `device_class:
   power` or `state_class: measurement`. Phase A/B power sensors have both. Without `state_class`,
   HA won't record long-term statistics for total power.

2. **Phase A voltage filter mismatch.** Phase A uses `[*pos, *pos]` (double pos, no smoothing) while
   Phase B uses `[*moving_avg, *pos]`. Probably a copy-paste oversight; Phase A voltage is
   unsmoothed.

3. **ESPHome names diverge from HA entity IDs for AC circuits.** ESPHome config names them "AC1",
   "AC2", "AC3" but HA entity IDs are `ac_master`, `ac_office`, `ac_upstairs` (renamed in the HA
   entity registry). The planned migration must use the HA-facing names in copy sensors, otherwise
   new entity IDs will be created and the old customized ones orphaned.

4. **CT03-CT05 friendly names lack "Emporia Vue 3" prefix.** All other CT sensors include the device
   prefix; these three do not. Cosmetic inconsistency.

5. **All entities assigned to "Small Garage" area.** The device is in the small garage (where the
   panel is), so all entities inherit that area. Circuits should be assigned to their destination
   areas instead.

## Area reassignment plan

Proposed mapping (device stays in Small Garage; entity-level overrides):

| Circuit(s)                          | Target area         |
| ----------------------------------- | ------------------- |
| Phase A/B, Total, Subpanel combined | Small Garage (keep) |
| CT01/02 Subpanel                    | Small Garage (keep) |
| CT03 AC Master                      | Master Bedroom      |
| CT04 AC Office                      | Office              |
| CT05 AC Upstairs                    | Upstairs (created)  |
| CT06 Oven                           | Kitchen             |
| CT07 Dryer                          | Laundry Room        |
| CT08/09 Pool                        | Pool Equipment      |
| CT10 Server                         | Server Room         |
| CT11 Ice Maker                      | Laundry Room        |
| CT12 Media Fridge                   | Media Room          |
| CT13 Garage GFI                     | Small Garage (keep) |
| CT14 Media 20a                      | Media Room          |

## Work log

### 2026-04-05

- Captured pre-migration baseline (above).
- Added `area` subcommand to `hass-api.py` (list, get, set with batch support via comma-separated
  entity IDs).
- Identified five issues in current config (above).
- Created "Upstairs" area in HA for CT05 AC Upstairs.
- Completed all area reassignments: 24 entities moved to destination areas.
- Added `area create` action to `hass-api.py`.
- Updated `home-assistant` skill doc with `area` and `activity` subcommands.
- Added `history` subcommand to `hass-api.py` (head/tail, --summary, --json modes).
- Cross-referenced all migration claims against upstream repo; 6/7 fully confirmed, 1 partially (Vue
  3 I2C pins not in upstream docs, confirmed via digiblur).
- Applied ESPHome filter migration to `vue3.yaml`:
  - CT clamp power sensors made internal (id only, no name, no moving average).
  - Added copy sensors with `throttle_average: 5s` for HA display.
  - Added `on_update` trigger for synchronous `total_power`/`balance_power` updates.
  - Changed `total_power` to `update_interval: never`, added `device_class`/`state_class`.
  - Added `balance_power` template sensor (total minus all CTs).
  - Added `throttle: 60s` to all `total_daily_energy` sensors.
  - Fixed Phase A voltage filter (`[*pos, *pos]` -> `[*moving_avg, *pos]`).
  - Renamed AC circuits from generic (AC1/AC2/AC3) to descriptive (AC Master/Office/Upstairs).
  - Removed unused filter anchors (`&invert`, `&abs`) and `substitutions` block.

- Confirmed device running clean after OTA flash (no errors in logs).
- Investigated post-flash entity state: CT01-02 and CT06-14 kept old entity IDs; CT03-05 got new IDs
  with `emporia_vue_3_` prefix (due to rename from AC1/AC2/AC3 to AC Master/Office/Upstairs). Old
  CT03-05 entities fully removed from HA (no orphans).
- Verified HA helper sensors (`ct_power_subpanel`, `ct_usage_pool`, `ct_usage_subpanel`) still
  working correctly; they reference CT01/02/08/09 which kept their IDs.
- Added `energy` subcommand to `hass-api.py` (get, validate, set via WebSocket
  `energy/get_prefs`/`energy/save_prefs`).
- Fixed Energy dashboard: replaced 3 broken CT03-05 entity references, added `balance_daily_energy`.
  Validation passes clean.
- Refactored `hass-api.py` for DRY: extracted `ws_send` into `ws_call` (eliminated 5 duplicate
  closures), added `_ws_error` helper, `_parse_time_arg` helper, moved repeated imports to
  top-level. 1112 -> 1051 lines.
- Area assignments still intact for CT01-02/CT06-14 (entity IDs unchanged). New CT03-05 entities
  need area reassignment.
- Captured post-migration baseline (above).

**Remaining TODO:**

- Reassign areas for new CT03-05 entities and CT13 Garage GFI.
- Update Outline doc with completed migration and findings.

## References

- Outline doc: "Emporia Vue 3 (ESPHome)"
- [emporia-vue-local/esphome upstream][upstream]
- [ESPHome config: vue3.yaml][config]

[upstream]: https://github.com/emporia-vue-local/esphome
[config]:
    https://github.com/rcdailey/home-ops/blob/main/kubernetes/apps/home/esphome/config/vue3.yaml
