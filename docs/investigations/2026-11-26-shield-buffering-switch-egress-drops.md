# Shield Buffering from Switch Egress Drops

- **Date:** 2026-11-26
- **Status:** PARTIALLY RESOLVED

## Summary

The living room Shield stalled repeatedly while playing Marshals in Plex and Silo, and once more
after switching to Paradise. The stalls overlapped a SABnzbd download of about 470 Mbps on hanekawa,
the node that also runs Silo. Switch ports where 10 GbE traffic steps down to slower links dropped
packets during playback. Nezuko now uses CUBIC instead of BBR, and SABnzbd has a lower speed limit.
No controlled test proved that the drops caused the stalls.

## Symptoms

- Marshals S02E06 (4K HEVC Dolby Vision, about 25 Mbps) stalled repeatedly on the living room Shield
  in Plex, then in Silo. A Paradise episode started afterward stalled once, then played normally.
- The user reported the stalls at about 18:38 CST as happening within the previous 20 minutes. Plex
  last saved Marshals progress at 18:34:39, about 4 minutes into the episode.
- The UniFi port panel for the Shield's port showed a 24h anomaly score of 0 and "Excellent" in
  every category.

## Investigation

### Diagnosis script and Plex logs

`scripts/plex-client-diagnose.py` initially reported no failures and "0" pod packet drops and NFS
retransmissions. Neither metric exists in VictoriaMetrics
(`container_network_*_packets_dropped_total` and `node_nfs_rpc_retransmissions_total`), and the
script treated an empty query result as zero.

The script also found 0 Plex server log records. The Plex OpenTelemetry sidecar parsed the zoneless
Plex log timestamps as UTC, so VictoriaLogs stored each record 6 hours early, and window queries
never matched it. The sidecar container runs in UTC, and the stanza timestamp parser defaults to the
local zone of the collector.

The script reads logs only from the media room Shield (192.168.1.105), so it could not have covered
this incident on the living room Shield (192.168.1.112). The media room Shield's log endpoint also
refused connections during the investigation.

### Mistaken first lead

The first pass attributed a 4K stream from 17:45 to 18:05 to the Shield. UniFi client and port
counters placed that stream on Switch Pro 48 port 33, a device on the Kids VLAN in Wyatt's room
linked at 100 Mbps. That port dropped 1,000 to 2,000 packets every 2 minutes while carrying 70 to 79
Mbps. The user confirmed that the playback was on the living room Shield, so this stream belonged to
another viewer.

UniFi controller counters update only every minute or two. Rate queries with 1 to 2 minute windows
placed traffic at the wrong times and contributed to the confusion. Queries with 3 to 5 minute
windows matched the Plex and Silo pod transmit rates.

### Shield sessions and drops

The Shield's port is Switch Pro 48 port 10, linked at 1 GbE. Corrected timeline:

| Time (CST)    | Source | Shield port traffic | Port 10 TX drops      |
| ------------- | ------ | ------------------- | --------------------- |
| 18:26 - 18:32 | Plex   | 7 - 33 Mbps         | none recorded         |
| 18:32 - 19:05 | Silo   | 5 - 36 Mbps         | 100 - 300 per 5 min   |

Port 10 recorded no drops in the 24 hours before this incident. On the switch,
`swctrl port show counters id 10` showed TX discards rising from 18,769 to 20,749 over the evening,
with 0 FCS, collision, MAC, and pause counts. The controller reported 16,901 TX drops out of 89.8M
packets (about 0.02%), with 0 TX and RX errors. The UniFi anomaly score does not appear to include
egress discards.

The packet path from Plex or Silo to the Shield:

1. Node to Cluster USW Flex 2.5G (2.5 GbE)
2. Cluster switch to Switch Pro 48 (10 GbE)
3. Switch Pro 48 to the UDM Pro (10 GbE), because LoadBalancer IPs are on 192.168.50.0/24 and the
   Shield is on 192.168.1.0/24
4. UDM Pro back to Switch Pro 48 (10 GbE)
5. Switch Pro 48 port 10 to the Shield (1 GbE)

The 10 GbE links in steps 2 to 4 recorded no drops from 18:20 to 19:05. Port 10 was the only drop
point on the Shield's path.

### Concurrent bulk traffic

From 18:34 to 18:45, SABnzbd on hanekawa downloaded at about 473 Mbps, and hanekawa's client traffic
totaled about 807 Mbps. Nezuko carried about 500 Mbps in the same window. Silo also runs on
hanekawa. The cluster switch port to hanekawa (`Hanekawa-2.5G`) recorded 101 and 136 TX drops in two
of the 5-minute buckets in that window. That port is where the NAS (10 GbE) and the router (10 GbE)
both send to a 2.5 GbE node. The port to marin (`Marin-2.5G`) also dropped 91 to 348 packets per 5
minutes between 18:30 and 18:40. Marin hosts Plex.

### Controlled playback check

At 20:37 the user replayed Marshals on the Shield, this time through Silo. Over about 5.5 minutes,
port 10 dropped 665 packets out of about 336,000 sent (about 0.2%), and playback did not stall. Silo
sent 2 to 19 Mbps during the check. Port 10 drops alone did not cause visible stalls at this rate.

### Switch buffer

The Switch Pro 48 (US48PRO) reports `cpu=BCM56160` in `/proc/ubnthal/system.info`. Broadcom's
product brief lists a 2 MB packet buffer per BCM56160, or 4 MB in the two-chip 48-port
configuration, which matches Ubiquiti's 4 MB figure. In Broadcom's OpenBCM SDK 6.5.16
(`hurricane3.c`), the default lossy MMU settings for BCM56160 use 128 B cells and cap each egress
queue at 1,676 cells (about 214 KB). The per-port dynamic limit equals the whole dynamic pool, so
idle ports hold almost no buffer. Ubiquiti's actual MMU configuration is not public.

With a 2.5 GbE source and a 1 GbE egress port, a queue grows at up to 1.5 Gbps and fills 214 KB in
about 1.1 ms. A burst longer than about 350 KB at 2.5 Gbps would overflow it.

UniFi exposes per-port TX discard counters but no queue occupancy, high-water marks, or per-queue
drop counters. `swctrl` help listed no queue or buffer commands. The switch has no `iperf3`.

### Sender behavior

Cilium Bandwidth Manager runs on the nodes (`EDT with BPF [CUBIC] [bond0]`), so pods use fq pacing
with CUBIC. Without a pod bandwidth annotation, Cilium applies no rate limit. Linux sets the pacing
rate from the congestion window and round-trip time. On a LAN with sub-millisecond RTT, that rate
can exceed the 1 GbE or 2.5 GbE step-down, so pacing does not prevent these bursts.

Nezuko (Unraid 7.4, kernel 6.18.60) used BBR with fq. CUBIC was not loaded
(`tcp_available_congestion_control = reno bbr`), and no Unraid config set the value. BBR keeps
sending at its bandwidth estimate during loss, while CUBIC reduces its window on loss.

### Controlled switch test

On 2026-11-27, `scripts/switch-buffer-test.py` sent a steady 40 Mbps UDP stream from Nezuko to
hanekawa for 60 seconds, once alone and once while Nezuko and the UDM Pro pushed 8 parallel TCP
streams each into hanekawa:

| Run              | Stream loss | Bulk received      | `Hanekawa-2.5G` TX drops |
| ---------------- | ----------- | ------------------ | ------------------------ |
| Stream alone     | 0.11%       | none               | 0                        |
| With bulk        | 1.66%       | 0.71 + 1.48 Gbps   | 13,673 of 14.2M packets  |

The bulk senders retransmitted about 256,000 segments. The loss in the stream-alone run happened
somewhere other than this port.

The first attempt reported 0 drops under load because, for a few minutes, the Cluster USW Flex 2.5G
controller counters showed about 1 Mbps on its uplink while the Switch Pro 48 sent it 3.4 Gbps. The
switch had run for 371 days and was restarted before the next run. Hourly counts at both ends of
that link agreed within about 10% from 2026-11-20 on, so the counters were not stuck for long. The
controller collects switch counters only every 1 to 2 minutes, so short windows can disagree.

The Flex 2.5G, USW Ultra, and Flex Minis (firmware 2.1) refuse SSH before the key exchange;
Ubiquiti's Flex Mini datasheet states it does not support SSH.

### Related report

A Home Operations Discord thread described the same pattern on a USW-Enterprise-24-PoE (2 MB
buffer): video to a slow client stalled while 2.5 GbE hosts ran heavy transfers through the switch.
Flow control and the choice between BBR and CUBIC on test clients made no difference there. The
reporter later stated that switching the NAS to CUBIC "pretty much fixed it", and that
per-destination traffic shaping would be the more targeted fix.

## Root Cause

Not proven. The supported explanation is egress buffer overflow on shallow-buffer UniFi switch ports
where traffic steps down in speed, made worse by bulk transfers that share the media server's node
link:

- Ports where 10 GbE traffic meets a 2.5 GbE node (`Hanekawa-2.5G`, `Marin-2.5G`) dropped packets
  while SABnzbd downloaded and Nezuko carried about 500 Mbps. Silo's NFS reads from Nezuko cross the
  hanekawa port.
- Port 10 to the 1 GbE Shield drops packets during any stream, but a 0.2% drop rate there did not
  stall playback without the bulk download.
- Nezuko used BBR, which keeps sending through loss.

The user accepted the SABnzbd and streaming overlap as the explanation without a controlled
reproduction, because coordinating a large download with playback was impractical.

## Resolution

- Nezuko uses CUBIC. A User Scripts entry named `tcp-cubic` runs at array start
  (`modprobe tcp_cubic` and `sysctl -w net.ipv4.tcp_congestion_control=cubic`), because Unraid loads
  its OS into RAM at boot and discards runtime changes. Existing connections keep BBR until they
  reconnect.
- SABnzbd's percentage of line speed went from 70 to 50 (40 MB/s of the 80 MB/s maximum). This
  setting lives in `sabnzbd.ini` on the app PVC, not in Git.
- `scripts/plex-client-diagnose.py` reports a missing metric as unavailable instead of zero. It
  queries `k8s_pod_network_errors_total` for the Plex pod and no longer queries NFS retransmissions,
  which no collector provides.
- The Plex collector parses log timestamps with `location: America/Chicago`
  (`kubernetes/apps/media/plex/collector.yaml`). Records stored before the change keep the wrong
  time.

Options not taken:

- Flow control. Ubiquiti recommends it for mismatched link speeds, but it pauses the whole sending
  link, and it made no difference in the related Discord report.
- A different switch. No candidate UniFi model publishes per-port buffer limits, and the cause was
  not proven well enough to justify the cost.
- Moving LoadBalancer IPs onto the client VLAN to avoid the router hop. The router links showed no
  drops, so this would not change the step-down at the Shield.

The controlled switch test confirmed that bulk TCP into a node drops packets from a concurrent
stream at its 2.5 GbE port. It did not show that this loss stalls the Shield. Rerun
`scripts/switch-buffer-test.py` after each mitigation to compare.

Remaining options:

- Per-destination traffic shaping on Nezuko, so Nezuko alone cannot fill a node's 2.5 GbE link.
- 10 GbE node links. Every node (four NUC8 models and one NUC7i5BNH) has a Thunderbolt 3 controller
  linked at PCIe 3.0 x4, enough for a Thunderbolt 10 GbE adapter; the current USB 2.5 GbE adapters
  run over 5 Gbps USB. This needs five adapters at about 200 USD each and a switch such as the USW
  Pro XG 8 PoE (eight 10 GbE RJ45 ports, two SFP+ uplinks, 2 MB buffer) in place of the Flex 2.5G,
  about 1,500 USD in total. It removes the 10 to 2.5 GbE step-down but not the 10 to 1 GbE step-down
  at the Shield.

A Cilium bandwidth cap does not apply here: it limits only traffic that pods send, and the drops are
on traffic arriving at the node.

## Lessons Learned

- In Ethernet, each link negotiates its own speed. A sender transmits bursts at its own link rate,
  and TCP controls only the average rate, so every speed step-down needs buffer for those bursts.
- Before trusting a zero from a metric query, confirm that the query returned a series.
- Short rate windows on UniFi port counters misplace traffic in time. Use windows of 3 minutes or
  more.
- Confirm which client a stream belongs to before correlating drops with a user's report.

## References

- [Cilium issue #27800][cilium-27800]
- [Broadcom BCM56160 product brief (PB100-R)][bcm56160-pb]
- [OpenBCM SDK 6.5.16 `hurricane3.c`][openbcm-hr3]
- [UniFi Switch Pro 48 tech specs][usw-pro-48]
- [UniFi Flow Control help article][unifi-flow-control]
- [Linux IP sysctl documentation (TCP pacing ratios)][kernel-sysctl]
- [ESnet: interface speed mismatch][esnet-mismatch]
- [Earlier Shield buffering investigation][prior-shield]
- [Media Flex port flapping investigation][media-flex]

[cilium-27800]: https://github.com/cilium/cilium/issues/27800
[bcm56160-pb]: https://docs.broadcom.com/docs-and-downloads/collateral/pb/56160-PB100-R.pdf
[openbcm-hr3]: https://github.com/Broadcom-Network-Switching-Software/OpenBCM/blob/6d2330ce1b4fc49d681cffcf09af408661be4c62/sdk-6.5.16/src/soc/esw/hurricane3.c
[usw-pro-48]: https://techspecs.ui.com/unifi/switching/usw-pro-48?subcategory=all-switching
[unifi-flow-control]: https://help.ui.com/hc/en-us/articles/26884644878615-Flow-Control
[kernel-sysctl]: https://www.kernel.org/doc/html/latest/networking/ip-sysctl.html
[esnet-mismatch]: https://fasterdata.es.net/performance-testing/troubleshooting/interface-speed-mismatch
[prior-shield]: ./2026-05-12-plex-shield-buffering-lan-classification.md
[media-flex]: ./2026-04-18-media-flex-port-flapping.md
