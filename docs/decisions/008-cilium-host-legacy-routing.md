# Use Hybrid BPF Routing (hostLegacyRouting: true)

- **Status:** Accepted
- **Date:** 2025-11-21
- **Decision:** Use `bpf.hostLegacyRouting: true` for hybrid BPF/kernel routing

## Context and Problem Statement

Cilium supports two routing modes: full BPF routing (`hostLegacyRouting: false`) where all traffic
passes through the BPF datapath, and hybrid routing (`hostLegacyRouting: true`) where BPF handles
what it can and falls back to kernel routing otherwise. During the BBR investigation, full BPF
routing was tested. The BGP migration later reverted to hybrid routing for stability.

## Considered Options

- **Hybrid routing (hostLegacyRouting: true)** - BPF + kernel fallback
- **Full BPF routing (hostLegacyRouting: false)** - BPF-only datapath

## Decision Outcome

Chosen option: **Hybrid routing**, because it provides the safest path for BGP peering with the UDMP
gateway. Full BPF routing was briefly used during the BBR experiment but the BGP migration (commit
`691bf49`) reverted to hybrid for compatibility.

Advanced features that require full BPF routing (netkit, BigTCP) were tested and failed. Netkit
requires `socketLB.hostNamespaceOnly: false` which conflicts with Talos's `forwardKubeDNSToHost` DNS
architecture. BigTCP required GSO/GRO offload which conflicted with Intel e1000e NIC patches at the
time (those NICs were later replaced with USB-C r8152 adapters in commit `08065c6`, potentially
removing the BigTCP blocker).

## Consequences

- Good, because proven stability with BGP peering
- Good, because avoids netkit/socketLB DNS conflict
- Bad, because slightly less efficient than full BPF routing
- Bad, because prevents enabling netkit device mode

Revisit if: netkit adds support for `socketLB.hostNamespaceOnly: true`, or if BigTCP is needed and
can be validated with the current r8152 NIC drivers.

## References

- [BBR investigation][investigation] (netkit/BigTCP failure details)
- Commit `691bf49`: BGP migration that set hostLegacyRouting: true
- Commit `08065c6`: NIC replacement removing e1000e GSO/GRO constraint

[investigation]: /docs/investigations/cilium-bbr-timeout-investigation-2025-11-14.md
