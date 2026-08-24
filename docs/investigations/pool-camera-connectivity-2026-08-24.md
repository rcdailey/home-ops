# Pool camera connectivity failure

- **Date:** 2026-08-24
- **Status:** UNRESOLVED

## Summary

The pool camera had intermittent connectivity to the UNVR before going offline. Switch counters
show severe frame corruption on traffic received from the camera. Moving the connection to another
switch port and a different set of switch-side patch cables did not fix the problem, narrowing the
fault to the long cable path or the camera.

## Symptoms

- The pool camera was intermittently connected to the UNVR and later appeared offline.
- Power cycling the PoE port did not restore connectivity.
- The camera initially negotiated at 1 Gbps on switch port 19. After moving to port 21, it
  negotiated at only 100 Mbps.
- PoE remained healthy on both switch ports.

## Investigation

`unifly` identified the affected devices and their physical connections:

| Device | Network | Switch port |
| --- | --- | --- |
| Pool camera | Cameras VLAN | 19, then 21 |
| UNVR camera interface | Cameras VLAN | 52 |

Ports 19 and 52 were access ports on the Cameras network, VLAN 5. The UNVR port was forwarding at
10 Gbps with no FCS errors, which eliminated the UNVR link as the source of corruption. Other camera
ports on the same switch also had zero or negligible errors.

Direct switch counters on port 19 showed 46,784,146 RX FCS errors. A 10-second sample recorded 452
successful RX frames and 112 additional FCS errors, so about 20% of frames arriving from the camera
were corrupt during that interval:

```sh
./scripts/unifi-ssh.sh -f \
  'RX Pkt Successfully|RX Total Error|RX FCS Error' \
  <switch-ip> swctrl port show counters id 19
```

Port 19 remained linked at 1 Gbps full duplex. PoE was healthy at 53.75 V and 4.30 W. The
combination of stable PoE and rising FCS errors showed that power delivery was not the cause.

The camera was moved to port 21 using a completely different set of switch-side patch cables. Port
21 was configured as an access port on VLAN 5 with the same VLAN management restrictions as port 19.
Power cycling PoE did not bring the camera online.

Port 21 linked at 100 Mbps full duplex and supplied healthy PoE at 52.50 V and 4.20 W. The switch
received traffic from the camera, but none of it passed frame validation. During a 10-second sample,
the counters changed as follows:

| Counter | Increase |
| --- | ---: |
| Successful RX frames | 0 |
| Total RX errors | 1,295 |
| RX FCS errors | 753 |
| RX alignment errors | 372 |
| RX fragments | 164 |

Because the switch could not decode a valid frame on port 21, UniFi continued to show the camera's
last valid association on port 19. That stale association did not indicate that the camera was still
physically connected there.

## Root Cause

The exact failed component is not yet confirmed. The fault is at the Ethernet physical layer and is
limited to one of the two components that remained after the port move:

1. The long cable path, including its terminations.
2. The camera's Ethernet interface.

The VLAN configuration, UNVR link, switch port, switch-side patch cables, and PoE supply have been
eliminated. The high FCS, alignment, and fragment error rates mean the switch receives electrical
signals from the camera but cannot decode valid Ethernet frames.

## Resolution

The investigation stopped pending a physical substitution test. Either test will isolate the failed
component:

1. Temporarily connect the pool camera beside the switch using a known-good short PoE cable. Clean
   counters would implicate the long cable path; continued errors would implicate the camera.
2. Connect a known-good spare PoE camera at the pool end of the existing long cable. Clean counters
   would implicate the pool camera; continued errors would implicate the cable path.

A basic continuity tester may not detect this fault. Ethernet can maintain PoE and negotiate a link
while signal integrity is too poor to carry valid frames. A cable qualifier that measures each pair
under Ethernet signaling is a useful alternative if neither substitution test is practical.

## Lessons Learned

- A healthy PoE reading and an active link do not prove the data path is healthy.
- RX FCS errors on a switch port identify corruption on frames arriving from the connected device.
- Moving both the switch port and switch-side patch cables is an effective way to eliminate those
  components without disturbing a long in-wall run.
- The related Media Flex investigation found that current USW Pro 48 PoE firmware does not expose a
  usable cable diagnostic, so physical substitution remains the practical isolation method.

## References

- [Media Flex Mini uplink port flapping investigation][media-flex-investigation]

[media-flex-investigation]: media-flex-port-flapping-2026-04-18.md
