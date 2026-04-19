# Media Flex Mini uplink port flapping

- **Date:** 2026-04-18
- **Status:** UNRESOLVED

## Summary

The Media Flex Mini's uplink to Switch Pro 48 port 6 has been dropping link ~8 times per hour over
the past 10 days. PoE stays up through the drops, so the Flex never fully reboots, but data
connectivity cuts out. Disabling auto-negotiation changed the symptom (previously auto-negotiated
down to 100M and stuck there) but did not fix the underlying cause. Evidence points to a
physical-layer fault somewhere on the 1000BASE-T path, most likely a failing pair at one of the
hand-terminated punchdowns. No fix yet; diagnostic plan is below.

## Symptoms

- Data link to Media Flex Mini cuts out intermittently; PoE continues to power the device.
- Previously (with auto-negotiation enabled): link negotiated down to 100M and never renegotiated
  back up to 1G without physically unplugging the cable.
- After forcing 1G with auto-negotiation disabled: link stays at 1G when up, but drops completely
  and retrains multiple times per hour.

## Investigation

Collected the following evidence via `unifly` (UniFi controller API) and direct SSH to the switch.

Port counters on Switch Pro 48 port 6, compared to every other active port on the same switch:

| Metric | Port 6 (MediaFlex) | Typical 1G port | 10G SFP+ uplinks |
| --- | --- | --- | --- |
| `link_down_count` | 2058 | 0-3 | 1-3 |
| `stp_state_change_count` | 649 | 3-7 | 3 |
| `autoneg` | false | true | false |
| `rx_errors` / `tx_errors` | 0 / 0 | 0 / 0 | 0 / 0 |
| `tx_dropped` | 5165 | ~0 | ~0 |

Switch uptime at the time of measurement: 10.5 days. That's roughly 8 link-down events per hour on
port 6, while other ports on the same switch (same firmware, same PoE budget, same everything) are
stable.

MAC-level counters from `swctrl port show counters id 6` on the switch directly:

```txt
RX FCS Error:         0     TX FCS Error:         0
RX Alignment Errors:  0     TX Total Collision:   0
RX Jabbers/Fragments: 0     TX Pkt Discard:    5260
RX Pkt Discard:       0
```

Zero corruption at the MAC layer. When the link is up, every frame is clean. The link just fails
entirely and retrains.

PoE is healthy: `poe_good: true`, 1.90 W at 51.35 V, 37 mA draw. PoE survives every drop, which is
consistent with the user's observation that the device stays powered.

Media Flex Mini's own uptime is only ~15 hours while the switch has been up for 10.5 days, so the
Flex is the side losing the link, not the switch.

Tried to run a cable test via the UniFi Network UI and via the switch's own firmware. The UI button
is gone (Ubiquiti removed it from USW Pro 48 PoE in firmware 8.x+). The switch's `swctrl` utility
has no cable diagnostic subcommand. `devshell` on the `switchdrvr` process requires symbol tables
that aren't present. No `ethtool` / `mii-tool` / `phytool` on the device. Cable diagnostics on this
generation are effectively unavailable.

## Root Cause

Not yet confirmed. The evidence fits a single-pair physical fault on the run to the Media Flex
Mini, most likely at one of the hand-terminated punchdowns.

1000BASE-T uses all four pairs of the cable with PAM-5 signaling and requires all four to train
successfully. 100BASE-TX only uses two pairs (pins 1/2 and 3/6). If one of the 1000BASE-T-only pairs
(pins 4/5 or 7/8) is broken, intermittently open, or has enough crosstalk to fail PAM-5 training,
the behavior is exactly what we observe:

- With auto-negotiation on, the PHYs try 1000BASE-T, fail training on the bad pair, fall back to
  100M (which doesn't need the bad pair), and stay at 100M because further retraining keeps
  failing. Only a full unplug/replug reruns negotiation from scratch and briefly catches a window
  where the pair works.
- With 1G forced, the PHY is required to train all four pairs. When the bad pair fails, the whole
  link drops and retrains. No corrupt frames are passed because the link doesn't stay up long
  enough to pass bad data; it just fails training and starts over. That matches `rx_errors=0,
  tx_errors=0, link_down_count=2058`.
- PoE runs on the same pairs but only needs DC continuity, which tolerates crosstalk and return
  loss that would kill gigabit PAM-5. PoE staying up while data drops is consistent with, not
  contradictory to, a marginal pair.

### The physical path

In reverse from the Media Flex Mini:

```txt
[Media Flex Mini]
  |-- RJ45 plug
  4-6 ft Cat6a patch cable (factory)
  |-- RJ45 plug
[Keystone jack in media cabinet]  <-- hand-punched by owner
  |
  50-100 ft in-wall/attic Cat6a run (2nd floor -> attic -> 1st floor server room)
  |-- RJ45 male plug (crimped by low-voltage contractor during construction)
[Feed-through keystone panel A, server room]  <-- 1U 24-port, factory-loaded shielded keystones
  |-- RJ45 port
  3-4 ft Cat6a patch cable (factory)
  |-- RJ45 plug
[Feed-through keystone panel B, server room]  <-- 1U 24-port, factory-loaded shielded keystones
  |-- RJ45 port
  2 in Cat6a patch cable (factory)
  |-- RJ45 plug
[Switch Pro 48, port 6]
```

Both server-room panels are Cat6a feed-through shielded patch panels (1U 24-port) pre-loaded with
factory keystones. Feed-through means each keystone is female on both sides, so cables plug in on
both ends with no punchdown step. No hand-terminated connections exist in the server room at all.

Only two hand-terminated points exist in the full path: the RJ45 male plug(s) crimped onto the
in-wall run by the low-voltage contractor at build time, and the keystone jack in the media cabinet
that the owner punched down himself. Every short patch cable was purchased factory-terminated.

Side note: feed-through shielded keystones rely on a bonded shield from end to end for the
shielding to work. If the panels are not grounded to the rack and the in-wall run isn't using STP,
the shielding does nothing. This doesn't cause the flapping symptom by itself (other ports on the
same panels are stable), but it's worth noting if future EMI issues come up.

In order of probability:

1. The contractor-crimped RJ45 male plug on the in-wall run. RJ45 male plugs on solid-core in-wall
   cable are the single most failure-prone termination style: solid copper is designed for
   insulation-displacement punchdown, and the sharp contacts on a male plug can work loose or
   oxidize over time on a single strand of one pair. Likely candidate #1.
2. The owner-punched keystone jack in the media cabinet. Home-punched terminations often have at
   least one wire that wasn't seated firmly, which can degrade gradually.
3. The long in-wall/attic run itself. Physical damage (staple through jacket, kink at a sharp bend,
   rodent in the attic section) is uncommon but possible given the attic environment.
4. Port hardware (PHY/magnetics) on either the 48-port switch or the Media Flex Mini is failing.
   Least common, but possible.
5. Bad factory crimp on one of the three short patch cables in the path. Rare for new cable.

## Resolution

Not yet resolved. A full end-to-end bypass test (temporary patch cable on the floor from the switch
to the Flex) was ruled out due to low WAF, so the plan below narrows things down progressively
without running visible cables through the house. Steps are ordered cheapest and least invasive
first; wait 12-24 hours between steps and recheck `link_down_count` to see whether the change
helped.

### Step 1: move to a different port on the 48-port switch

Unplug the 2 in patch from port 6 and plug it into a spare port (e.g. port 12). Rename the new
port in UniFi to keep the naming convention tidy. Entirely inside the rack.

- If drops stop: port 6's PHY is failing. Leave the Flex on the new port and retire port 6.
- If drops continue: switch port hardware is fine. Continue to step 2.

### Step 2: swap the 2 in patch between switch and coupler row B

Inside the rack. Replace with any other known-good patch cable.

- If drops stop: bad short patch cable.
- If drops continue: continue to step 3.

### Step 3: bypass coupler row B

Inside the rack. Remove both the 2 in patch and the 3-4 ft patch between the coupler rows. Run a
single patch cable directly from coupler row A to the switch, skipping row B entirely.

- If drops stop: one of the couplers on row B is flaky (possible but uncommon for factory parts).
  Leave the bypass in place.
- If drops continue: continue to step 4.

### Step 4: swap the 3-4 ft patch between the coupler rows

If step 3 didn't eliminate it (e.g. if you chose to keep row B in the path), replace this patch
cable.

### Step 5: swap the 4-6 ft patch at the Media Flex end (already tried)

Already attempted before this investigation started. Owner swapped the patch cable between the
Media Flex and the media-cabinet keystone jack; drops continued. This patch cable is eliminated as
the cause. Skip.

### Step 6: re-terminate the media room keystone jack

Pop the jack out of the wall plate, cut the punchdown, re-punch the 8 wires. Requires a punchdown
tool (~$15).

### Step 7: re-crimp the RJ45 male plug on the in-wall run

Inside the rack. The in-wall run terminates in a contractor-crimped RJ45 male plug that plugs into
coupler row A. Cut the plug off and crimp on a fresh one (requires a crimper and an RJ45 plug
rated for solid-core cable). Given that this is suspect #1 in the probability ranking, you may
choose to do this step before steps 5 and 6.

### Step 8: replace the in-wall run

Last resort. If steps 1-7 all fail, the permanent cable is damaged and needs to be re-pulled.

## Lessons Learned

- Ubiquiti quietly removed cable diagnostics from the UniFi Network UI and from the USW Pro 48 PoE
  firmware. The `swctrl` utility on the switch has no cable test subcommand on current firmware.
  There's no API endpoint that returns cable test results either. If you need actual cable
  diagnostics (per-pair length, open/short, NEXT), you need either a hardware cable qualifier
  (Fluke, Pockethernet) or you need to do a physical swap test.
- `link_down_count` with clean MAC error counters is a strong diagnostic signature for PHY training
  failures, which usually mean a physical-layer fault on one of the pairs, not signal corruption.
  Don't anchor on "no errors logged" to conclude the cable is fine; the absence of FCS/alignment
  errors combined with high flap counts is actually the opposite signal.
- Asymmetric auto-negotiation settings (one end forced, one end auto) don't cause drops like this
  on their own when both ends resolve to the same speed and duplex. The flaps here happen whether
  auto-negotiation is on or off; only the symptom changes (stuck at 100M vs. dropping entirely).
- The `hops` CLI doesn't currently have a UniFi domain. `unifly` covers the controller API, and
  `scripts/unifi-ssh.sh` wraps direct switch SSH with a timeout and remote `grep`/`head` filters
  (ripgrep isn't available on the switch). A future `hops unifi` domain could wrap both for common
  port diagnostic queries.

## References

- [unifly CLI][unifly]: UniFi controller CLI used to query port state and counters.
- [Switch SSH helper][unifi-ssh]: repo-local wrapper around `ssh admin@<switch>` with BusyBox-safe
  filter flags.
- [UniFi link-speed alert rules][vmrules]: Prometheus rules that watch for negotiated speed
  degradation on labeled ports.

[unifly]: https://github.com/hyperb1iss/unifly
[unifi-ssh]: ../../scripts/unifi-ssh.sh
[vmrules]: ../../kubernetes/apps/observability/vmrules/unifi-alerts.yaml
