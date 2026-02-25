# Migrate from AdGuard Home to Blocky for DNS Filtering

- **Status:** Accepted
- **Date:** 2026-02-07
- **Decision:** Replace AdGuard Home + adguardhome-sync with Blocky for stateless, GitOps-native DNS
  filtering

## Context and Problem Statement

AdGuard Home serves as the cluster DNS filter with a 2-replica StatefulSet synchronized by
adguardhome-sync. While functional, it consumes ~300MB+ memory per replica, requires an imperative
sync sidecar to replicate configuration, and exposes a web UI that is unused (query lookups are done
via PostgreSQL). The architecture needs a DNS filter that treats configuration as code without
imperative state management.

## Considered Options

- **Blocky** - Stateless DNS proxy with YAML-only configuration, CIDR-native client groups,
  PostgreSQL query logging
- **AdGuard Home + adguardhome-sync** - Current architecture with polling-based config sync
- **Technitium DNS v14** - Native clustering, rejected in [ADR-002][adr-002] due to DANE-EE TLS
  incompatibility with Envoy Gateway HTTPRoutes

## Decision Outcome

Chosen option: **Blocky**, because it eliminates imperative state management and provides
CIDR-native client grouping that maps directly to VLAN subnets.

AdGuard Home's configuration is inherently imperative: filtering rules, client definitions, and
upstream settings live in a runtime database that must be synchronized between replicas via a
third-party polling tool. Blocky's entire configuration is a single YAML file rendered at pod
startup, making disaster recovery a `git checkout` away.

Blocky's `clientGroupsBlock` maps CIDR ranges directly to blocklist groups, replacing AdGuard Home's
per-client configuration that required manual maintenance through the web UI or adguardhome-sync.

PostgreSQL query logging (via CloudNativePG) replaces AdGuard Home's built-in query log UI with
structured SQL queries, enabling richer analysis through `blocky.py`.

## Consequences

- Good, because pure YAML configuration eliminates imperative state and sync tooling
- Good, because CIDR-native `clientGroupsBlock` maps directly to VLAN subnets
- Good, because stateless replicas require no coordination (each pod is independent)
- Good, because lower memory footprint (~87MB heap vs ~300MB+ per AdGuard Home replica)
- Good, because PostgreSQL query logging enables structured analysis
- Good, because `filterUnmappedTypes` natively solves the IPv6 CNAME leak that required custom
  AdGuard filtering rules
- Bad, because no web UI for ad-hoc query lookups (mitigated by `blocky.py`)
- Bad, because blocklist entry counts differ slightly between replicas due to independent fetching

## References

- [Blocky documentation][blocky-docs]
- [Blocky GitHub][blocky]
- [HaGeZi DNS blocklists][hagezi]
- [ADR-002: Previous DNS architecture decision][adr-002]
- [IPv6 CNAME leak troubleshooting][opencloud-ipv6]

[blocky-docs]: https://0xerr0r.github.io/blocky/latest/
[blocky]: https://github.com/0xERR0R/blocky
[hagezi]: https://github.com/hagezi/dns-blocklists
[adr-002]: /docs/decisions/002-dns-server-architecture.md
[opencloud-ipv6]: /docs/investigations/opencloud-desktop-ipv6-auth-failure-2026-01-25.md
