# Media room sconces stop reporting physical toggles

- **Date:** 2026-10-20
- **Status:** RESOLVED

## Summary

The media room sconce switch (Zooz ZEN77, Z-Wave node 21) changed the lights when its paddle was
pressed but never told the controller, so Home Assistant kept showing the old state. Z-Wave JS's
cached copy of the switch's Lifeline association listed the controller, but the switch's own
Lifeline group was empty. A re-interview restored the association, and every physical toggle has
reported since.

## Symptoms

- Turning the sconces off at the wall left `light.media_room_sconces` showing `on`.
- Asking the switch for its state (`zwave_js.refresh_value`) corrected Home Assistant immediately.
- The media room fan switch (node 24), mounted next to it, reported every physical toggle.

## Investigation

1. The switch's configuration parameters were correct: "Smart Switch Mode" was local and Z-Wave
   control enabled, and "Smart Bulb Mode: Reporting Behavior" was set to always report.
2. The association data Z-Wave JS returned (`controller.get_all_associations`) showed the Lifeline
   group (group 1) targeting node 1, the controller. This looked correct and was taken as fact for
   the rest of the routing work. It came from Z-Wave JS's cache, not from the switch.
3. The switch talked to the controller directly at -77 dBm with no repeaters, while the fan routed
   through nodes 3 and 9. Routing became the working theory.
4. A spare range extender (ZW189-C15, node 36) was moved three times. In the small garage and
   directly under the switch it could not reach the controller (`rebuild_node_routes` failed, ping
   failed). Halfway between the controller and the media room it answered at -70 dBm. Rebuilding
   routes for the extender and the switch still left the switch on a direct link.
5. Priority routes through node 36 were forced in both directions (`controller.set_priority_route`
   and `controller.assign_priority_suc_return_route`). Pings succeeded over the forced route, but
   physical toggles still produced no events. This ruled out routing.
6. Live event listening on node 21 during physical toggles showed nothing. A controller-initiated
   refresh during the same listen did produce value events, so the listener worked.
7. Driver debug logs captured a toggle test of both switches. Every frame came from node 24 (fan
   button presses and speed changes). No frame from node 21 arrived, encrypted or otherwise, so the
   controller was not rejecting the switch's reports; the switch was not sending them.
8. Querying the switch itself through the Association and Multi Channel Association command classes
   (`getGroup(1)` via `endpoint.invoke_cc_api`) returned an empty node list for the Lifeline group
   in both. The cache from step 2 disagreed with the device.
9. A re-interview from Z-Wave JS UI completed in about a minute. Afterward the switch's own Lifeline
   group listed node 1, a fourth association group appeared, and one more configuration parameter
   had a value. Eight physical toggles all reported within about a second.

## Root cause

The switch's Lifeline association was empty, so it had nowhere to send status reports when the
paddle was used. Z-Wave JS did not notice because it serves association data from its cache and does
not re-read it from the device. What cleared the association on the device is unknown.

## Resolution

- Re-interviewed node 21, which made Z-Wave JS re-add the controller to the Lifeline group.
- Removed the forced priority routes and reassigned automatic return routes. Clearing a node's
  return routes removes all of them, not just the forced one, so `scripts/zwave.sh route clear` now
  reassigns automatic routes afterward (commit `cbd87446`).
- Checked the other 13 mains-powered nodes the same way as step 8. Every Lifeline group matched the
  cache and targeted the controller. Battery nodes were skipped because they sleep.
- Added `scripts/zwave.sh` (commit `ca3ef963`) for the commands used here: node health, routes,
  pings, rebuilds, live event listening, and raw server commands.

## Lessons learned

- When a Z-Wave device stops reporting physical changes, compare its cached associations with the
  device's own before working on routes. `zwave.sh cmd endpoint.invoke_cc_api` with `commandClass`
  133 (Association) or 142 (Multi Channel Association), `methodName` `getGroup`, and `args` `[1]`
  reads group 1 from the device.
- A repeater only helps where it can reach both the controller and the device. Ping it after every
  move before rebuilding anything else.
- Driver debug logs show whether a device sent anything at all, which separates "not sent" from
  "sent but rejected".

## References

- [Z-Wave JS CLI][zwave-cli]

[zwave-cli]: ../../scripts/zwave/
