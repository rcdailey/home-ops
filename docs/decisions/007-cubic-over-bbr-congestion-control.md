# Use CUBIC over BBR for Intra-Cluster Networking

- **Status:** Accepted
- **Date:** 2025-11-14
- **Decision:** Use CUBIC congestion control (kernel default) instead of BBR for all cluster
  networking

## Context and Problem Statement

Plex 4K streaming experienced 30-second timeouts and VictoriaMetrics had 120-second write timeouts.
BBR was enabled system-wide via Talos sysctls (`net.ipv4.tcp_congestion_control: bbr`) to improve
throughput. Instead, a Linux kernel BBR stuck-state bug caused throughput collapse to 100 Kbit/s,
and Cilium Bandwidth Manager enforcement amplified the impact.

## Considered Options

- **CUBIC (kernel default)** - Conservative, loss-based congestion control
- **BBR** - Model-based congestion control optimized for high-bandwidth, high-latency links

## Decision Outcome

Chosen option: **CUBIC**, because BBR's stuck-state bug caused systemic failures and BBR is
optimized for WAN conditions (>50ms RTT) not intra-cluster networking (<2ms RTT).

BBR sysctls (`net.ipv4.tcp_congestion_control` and `net.core.default_qdisc: fq`) were removed from
Talos configuration. Cilium Bandwidth Manager remains enabled with EDT scheduling but without BBR
(`bbr: false` default).

## Consequences

- Good, because immediate resolution of all timeout issues across Plex and VictoriaMetrics
- Good, because CUBIC is well-tested for low-latency datacenter networking
- Good, because Bandwidth Manager with EDT still provides fair queuing without BBR
- Bad, because BBR's bandwidth estimation could theoretically improve bulk transfers
- Bad, because WAN-facing traffic (Cloudflare tunnel) also uses CUBIC

## References

- [BBR investigation][investigation]
- [Google BBR stuck-state discussion][bbr-stuck-state]
- [Cilium Bandwidth Manager documentation][cilium-bwm]

[investigation]: /docs/investigations/cilium-bbr-timeout-investigation-2025-11-14.md
[bbr-stuck-state]: https://groups.google.com/g/bbr-dev/c/XUOKHJiAW80
[cilium-bwm]: https://docs.cilium.io/en/stable/network/kubernetes/bandwidth-manager
