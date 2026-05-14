# Disable Talos host DNS forwarding for default BPF routing

- **Status:** Accepted
- **Date:** 2026-05-13
- **Decision:** Disable `forwardKubeDNSToHost` in Talos and remove Cilium's `hostLegacyRouting` and
  `socketLB.hostNamespaceOnly` overrides

## Context and Problem Statement

Three interlocked settings existed as workarounds for a Talos/Cilium incompatibility ([Talos issue
10002][talos-10002], [Cilium issue 36737][cilium-36737]). Talos's `forwardKubeDNSToHost` intercepts
pod DNS queries via a host-level proxy attached to loopback. Cilium's BPF routing bypasses loopback,
breaking that interception. The workaround was `hostLegacyRouting: true` (forcing packets through
the kernel stack so Talos could see them), which in turn required `socketLB.hostNamespaceOnly: true`
for compatibility. All three settings deviated from their respective defaults.

## Considered Options

- **Keep the workaround chain** -- no risk, but three non-default settings that interact in
  non-obvious ways and prevent BPF routing optimizations
- **Disable `forwardKubeDNSToHost`, remove both Cilium overrides** -- pods reach CoreDNS directly
  via ClusterIP instead of through the Talos host proxy; all three settings return to defaults

## Decision Outcome

Chosen option: **disable host DNS forwarding**, because it removes the root cause rather than
working around it. Both upstream issue threads ([Talos issue 10002][talos-10002], [Cilium issue
36737][cilium-36737]) confirm this as the accepted solution. The host proxy is a convenience for
edge cases during node bootstrap; once the cluster is running, CoreDNS handles all pod DNS
regardless of this setting.

## Consequences

- Good, because all three settings return to their defaults (less config to explain and maintain)
- Good, because BPF host routing is now active (lower CPU overhead per packet, slightly better
  latency)
- Good, because removes a known blocker for future Cilium features that require BPF routing (netkit,
  BigTCP)
- Bad, because during early node bootstrap (before CoreDNS is running), pods can't resolve DNS
  through the host proxy; in practice this only affects the initial cluster bootstrap, not normal
  operation

## References

- [Talos #10002: Cilium 1.16.5 breaks DNS with forwardKubeDNSToHost][talos-10002]
- [Cilium #36737: CoreDNS external queries fail after upgrading to 1.16.5][cilium-36737]
- [ADR-008: Use hybrid BPF routing (superseded)][adr-008]
- [BBR timeout investigation][investigation]

[talos-10002]: https://github.com/siderolabs/talos/issues/10002
[cilium-36737]: https://github.com/cilium/cilium/issues/36737
[adr-008]: /docs/decisions/008-cilium-host-legacy-routing.md
[investigation]: /docs/investigations/cilium-bbr-timeout-investigation-2025-11-14.md

## Historical Context

The workaround chain was established during the Nov 2025 BBR investigation. Attempts to disable
legacy routing (for BBR support) failed because `forwardKubeDNSToHost` was still active, breaking
DNS. A second attempt using netkit datapath also failed because `socketLB.hostNamespaceOnly` was
still set. A third attempt removing `socketLB.hostNamespaceOnly` ran into BBR's own issues with LAN
traffic. The final revert (commit `51ef5406`) restored all three settings to their conservative
values as a package.

The missing insight was that `forwardKubeDNSToHost` itself could be disabled safely. The Nov 2025
investigation focused on Cilium-side fixes without questioning the Talos setting. Both upstream
issue threads were closed by Jan 2025 with `forwardKubeDNSToHost: false` as the accepted resolution,
but that information wasn't incorporated until this ADR.
