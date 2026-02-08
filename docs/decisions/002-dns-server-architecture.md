# Retain AdGuard Home for DNS Server Architecture

- **Status:** Superseded by [ADR-004][adr-004]
- **Date:** 2026-01-05
- **Decision:** Continue with AdGuard Home + adguardhome-sync; reject Technitium v14 due to TLS
  termination incompatibility

## Context and Problem Statement

The cluster requires a DNS server providing ad-blocking, VLAN-based client filtering, query logging
with UI, and high availability. The solution must integrate with the existing external-dns
architecture (UniFi webhook to UDMP) and Envoy Gateway HTTPRoutes for web UI access. Technitium DNS
v14 (November 2025) introduced native clustering, prompting reevaluation of the current AdGuard Home
architecture.

Requirements:

- UI-based query lookups and statistics
- High availability with replication across cluster nodes
- GitOps-friendly for disaster recovery
- Compatible with Envoy Gateway HTTPRoutes and external-dns UniFi webhook

## Considered Options

- **AdGuard Home + adguardhome-sync** - Current architecture with polling-based config sync
- **Technitium DNS v14** - Native clustering with NOTIFY/IXFR replication
- **Pi-hole** - Requires third-party Gravity Sync, SQLite-based
- **Blocky** - No native UI for query lookups

## Decision Outcome

Chosen option: **AdGuard Home + adguardhome-sync**, because Technitium v14's TLS termination
restriction is incompatible with the cluster's Envoy Gateway HTTPRoute pattern.

Technitium explicitly states "you cannot terminate TLS at a HTTPS reverse proxy for the DNS web
service by design" due to DANE-EE for node-to-node connections. This is a fundamental architectural
conflict with how all cluster services expose their web UIs.

Additional factors against Technitium v14:

- Manual "Promote To Primary" required if primary fails (no automatic failover)
- No official Kubernetes guidance for StatefulSet configuration
- Clustering expects sequential pod startup, conflicting with `podManagementPolicy: Parallel`

Current architecture:

```txt
  +-------------------------------------------+
  |     adguard-home (StatefulSet, 2 replicas)|
  |  +-------------+      +-------------+     |
  |  |   Pod-0     |      |   Pod-1     |     |
  |  |  (Primary)  |      |  (Replica)  |     |
  |  +------+------+      +------+------+     |
  |         |                    ^            |
  |         +--------------------+            |
  |              adguardhome-sync             |
  +-------------------------------------------+
                    |
  +-------------------------------------------+
  |   external-dns (UniFi webhook) --> UDMP   |
  +-------------------------------------------+
```

## Consequences

- Good, because no migration risk or downtime
- Good, because proven stability since August 2025 with ongoing improvements
- Good, because full compatibility with Envoy Gateway HTTPRoutes
- Good, because full UI with query logs, VLAN-based filtering, 590k+ built-in rules
- Bad, because continued dependency on adguardhome-sync third-party tool
- Bad, because polling-based sync (10s interval) rather than real-time replication

Revisit this decision if Technitium adds reverse proxy TLS termination support, AdGuard Home adds
native clustering, or a new DNS server emerges with native HA, UI, and Kubernetes-native design.

## References

- [Technitium v14 Clustering Documentation][technitium-clustering]
- [Technitium v14 Release Notes][technitium-v14]
- [adguardhome-sync GitHub][adguardhome-sync]
- [Blocky DNS GitHub][blocky]

[technitium-clustering]: https://blog.technitium.com/2025/11/understanding-clustering-and-how-to.html
[technitium-v14]: https://blog.technitium.com/2025/11/technitium-dns-server-v14-released.html
[adguardhome-sync]: https://github.com/bakito/adguardhome-sync
[blocky]: https://github.com/0xERR0R/blocky
[adr-004]: /docs/decisions/004-blocky-dns-migration.md

## Historical Context

This decision follows multiple DNS server iterations since June 2025:

### Phase 1: k8s-gateway (June - August 2025)

Initial cluster DNS using k8s-gateway Helm chart. Provided basic internal service discovery but
lacked ad-blocking and VLAN-based filtering.

### Phase 2: Technitium DNS (August 2-10, 2025)

Implemented with NextDNS integration for subnet-based filtering (4 NextDNS endpoints with HaGeZi
blocklists, QUIC protocol, Advanced Forwarding plugin). Abandoned after 8 days due to complex
external-dns integration, NextDNS dependency, and fragile state management between Technitium zones
and external-dns.

### Phase 3: Blocky (Considered, Never Deployed)

Design document created for Blocky with custom external-dns webhook provider. Rejected due to no
native UI and requiring custom webhook development.

### Phase 4: AdGuard Home (August 16, 2025 - Present)

Current architecture: StatefulSet with 2 replicas, adguardhome-sync for config replication,
active-passive failover via HTTPRoute weights, built-in 590k+ filtering rules, real source IP
preservation for VLAN-based filtering, DNS record management delegated to UDMP via UniFi
external-dns webhook.
