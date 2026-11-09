# Plex Shield Buffering from WAN Misclassification

- **Date:** 2026-05-12
- **Status:** RESOLVED

## Summary

Nvidia Shield streaming from Plex buffered repeatedly because the Shield was connecting through the
HTTPS gateway (`plex.${SECRET_DOMAIN}:443`) instead of the direct LoadBalancer (`192.168.50.100:32400`).
The gateway path routes through Envoy, which terminates the client connection and opens a new one
to Plex. Plex sees the Envoy pod IP (10.42.x.x), classifies the session as WAN, and enables
bandwidth detection and quality throttling. Investigation also uncovered that the Plex
`LanNetworksBandwidth` CIDR (`192.168.0.0/19`) was based on a misunderstanding, and the Envoy
`externalTrafficPolicy: Cluster` was a stale workaround from the L2-to-BGP migration.

## Symptoms

- Intermittent buffering on Shield (media room) during movie playback
- Shield client logs showed `location=wan` on all requests
- `BandwidthDetectionBehaviour` cycling between quality profiles
- 5 buffering events totaling 18.9 seconds in one session
- `BufferingMetrics: bufferingDuration=18916, bufferingCount=5`

## Investigation

### Shield client logs

Fetched logs from the Shield's Plex client at `http://192.168.1.105:32500/logging`. All requests
went to `plex.${SECRET_DOMAIN}:443` (the external Envoy gateway at 192.168.50.73), never to the direct
LoadBalancer at `192.168.50.100:32400`.

The transcode decision requests showed `directPlay=0&directStream=0&location=wan`, meaning the
server was transcoding instead of direct playing a 25 Mbps source on a gigabit LAN.

The bandwidth detector thrashed in a loop: measure ~195 Mbps, upgrade to "Play Original Quality",
buffer drains because the gateway path adds overhead, underrun detected, downgrade to "Convert to
1080p HD", repeat.

### Why the Shield used the gateway path

The Shield's "Allow Insecure Connections" was set to "Never". Plex advertises two URLs via
`PLEX_ADVERTISE_URL`:

```yaml
PLEX_ADVERTISE_URL: http://192.168.50.100:32400,https://plex.${SECRET_DOMAIN}:443
```

With insecure connections blocked, the Shield refused the HTTP direct path and fell back to the
HTTPS gateway. After changing the Shield setting to "on the same network" and force-closing the Plex
app, the Shield reconnected via `https://192.168.50.100:32400` (Plex uses its own TLS cert for
direct connections), showing `location=lan`, `directPlay=1`, and 29+ seconds of buffer with zero
buffering events.

### The two access paths

There are two distinct network paths from a LAN client to the Plex pod:

**Direct LoadBalancer** (`192.168.50.100:32400`): Client -> UDMP BGP route -> Cilium DSR -> Plex
pod. DSR preserves the client's real source IP (e.g., 192.168.1.105). Plex sees a 192.168.x.x
address, matches `LanNetworksBandwidth`, classifies as LAN.

**HTTPS gateway** (`plex.${SECRET_DOMAIN}:443`): Client -> UDMP BGP route -> Envoy pod (L7 proxy,
terminates TLS) -> new TCP connection -> Plex pod. Plex sees the Envoy pod's IP (10.42.x.x), which
is outside any 192.168.x.x range, so it classifies as WAN regardless of LAN CIDR configuration.

Split DNS keeps gateway traffic on the LAN (UDMP resolves `plex.${SECRET_DOMAIN}` to
192.168.50.73), but the L7 proxy hop still masks the client's real IP at the application layer.

### The `/19` CIDR was unnecessary

The original `LanNetworksBandwidth=192.168.0.0/19` (commit `c140678d`, 2025-10-20) was designed to
exclude the BGP subnet (192.168.50.0/24) from LAN classification. The comment said: "excludes
192.168.50.0/24 (Kubernetes BGP/LoadBalancer subnet) to prevent plex.{SECRET_DOMAIN} from being
treated as local network traffic."

This reasoning had a gap. The `.50` subnet never appears as a source IP to Plex in either path:

- Direct LB: DSR preserves the real client IP (192.168.1.x), not the VIP (192.168.50.100)
- Gateway: Plex sees the Envoy pod IP (10.42.x.x), not the gateway VIP (192.168.50.73)

The `/19` was crafted to solve a problem that didn't exist. `192.168.0.0/16` works identically and
covers all local VLANs (Main .1, IoT .2, Kids .3, Guest .4, Cameras .5, Work .7, VPN .10).

The confusion likely originated from the networking stack change one week earlier. The cluster
migrated from L2 announcements to BGP (commit `691bf49b`, 2025-10-13), but the Envoy
`externalTrafficPolicy: Cluster` workaround for L2 issue #27800 was carried forward unchanged. The
stale context may have made it harder to reason about source IP behavior correctly.

### Stale externalTrafficPolicy: Cluster workaround

The Envoy gateway used `externalTrafficPolicy: Cluster` as a workaround for
[Cilium issue #27800][cilium-27800] (L2 announcements + Local incompatibility). The cluster
migrated to BGP seven months before this investigation, making the workaround unnecessary.

With BGP, `externalTrafficPolicy: Local` is safe because Cilium only advertises VIPs from nodes
that host the backing pod ([Cilium BGP docs][cilium-bgp-local]). The UDMP only receives routes from
nodes that can serve the traffic directly, so no cross-node forwarding or SNAT occurs.

Reference repos (onedr0p/home-ops) confirmed this: they run BGP + DSR + `externalTrafficPolicy:
Local` on Envoy Gateway.

## Root Cause

Two independent issues combined:

1. **Client-side:** Shield "Allow Insecure Connections" was set to "Never", forcing it through the
   HTTPS gateway path instead of the direct LoadBalancer. The gateway's L7 proxy masked the
   client's source IP, causing WAN classification, bandwidth throttling, and transcoding.

2. **Config-side:** The `LanNetworksBandwidth` CIDR (`192.168.0.0/19`) and `externalTrafficPolicy:
   Cluster` were both artifacts of reasoning that didn't survive the L2-to-BGP migration. Neither
   caused the buffering directly, but they made the setup harder to understand and debug.

## Resolution

**Client fix:** Changed Shield "Allow Insecure Connections" to "on the same network" and restarted
the Plex app. The Shield reconnected via the direct LoadBalancer with `location=lan` and zero
buffering.

**Manifest changes:**

- Simplified `LanNetworksBandwidth`, `LanNetworks`, and `PLEX_NO_AUTH_NETWORKS` from
  `192.168.0.0/19` to `192.168.0.0/16`. Rewrote comments to explain the two-path architecture.
- Switched Envoy `externalTrafficPolicy` from `Cluster` to `Local`. Removed stale L2 #27800 TODO.

## Lessons Learned

The `/19` exclusion survived seven months because it never caused a visible problem; it just didn't
do what the comment claimed. Stale workarounds from infrastructure migrations are easy to carry
forward and hard to notice until something forces a re-examination. The L2-era
`externalTrafficPolicy: Cluster` comment was similarly invisible until this debugging session
required tracing the full source IP path.

When Plex classifies a session as WAN vs LAN, the relevant question is "what source IP does the
Plex process see on the TCP connection?", not "what IP did the client connect to" or "is the client
on the same subnet." L7 proxies break the connection between those questions.

## References

- [Cilium DSR source IP preservation][cilium-dsr]
- [Cilium BGP: Local policy withdraws VIP from nodes without pods][cilium-bgp-local]
- [Cilium L2 announcements + externalTrafficPolicy: Local issue][cilium-27800]
- [onedr0p/home-ops Plex config][onedr0p-plex]
- [onedr0p/home-ops Envoy config (externalTrafficPolicy: Local)][onedr0p-envoy]

[cilium-dsr]: https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/
[cilium-bgp-local]:
    https://docs.cilium.io/en/stable/network/bgp-control-plane/bgp-control-plane-operation
[cilium-27800]: https://github.com/cilium/cilium/issues/27800
[onedr0p-plex]:
    https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/default/plex/app/helmrelease.yaml
[onedr0p-envoy]:
    https://github.com/onedr0p/home-ops/blob/main/kubernetes/apps/network/envoy-gateway/app/envoy.yaml
