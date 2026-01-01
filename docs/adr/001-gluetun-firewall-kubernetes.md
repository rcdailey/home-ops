# ADR-001: Gluetun Firewall Configuration for Kubernetes

**Status:** Accepted

**Date:** 2026-01-01

## Context

The qbittorrent application uses gluetun as a VPN sidecar container to route torrent traffic through
ProtonVPN. The original configuration disabled gluetun's built-in firewall and used incorrect subnet
values:

```yaml
FIREWALL_OUTBOUND_SUBNETS: 10.96.0.0/12,10.244.0.0/16
FIREWALL: "off"
```

### Problems

1. **Incorrect subnets**: `10.96.0.0/12` and `10.244.0.0/16` are default Kubernetes CIDRs
   (kubeadm/flannel), not the actual cluster CIDRs defined in `talos/talconfig.yaml`:
   - Pod CIDR: `10.42.0.0/16`
   - Service CIDR: `10.43.0.0/16`

2. **Disabled firewall**: `FIREWALL: "off"` was a workaround for Kubernetes networking issues.
   Without the firewall, there is no kill switch - if the VPN connection drops, traffic leaks
   unprotected to the internet.

### Historical Context

The firewall was disabled from the initial qbittorrent deployment (commit fcb78882) due to known
issues with gluetun's firewall blocking cluster traffic in Kubernetes environments:

- [GitHub Issue #254: Firewall and EXTRA_SUBNETS with Kubernetes sidecar][issue-254]
- [GitHub Discussion #2340: Enabling the firewall disables access to everything][discussion-2340]

[issue-254]: https://github.com/qdm12/gluetun/issues/254
[discussion-2340]: https://github.com/qdm12/gluetun/discussions/2340

## Decision

Enable gluetun's firewall with correct cluster CIDRs, leveraging first-class Kubernetes support
introduced in gluetun v3.41.0.

### Gluetun v3.41.0 Kubernetes Support

Released 2025-12-25, v3.41.0 introduced:

> **K8s users read this**: **Local network names resolution** using private DNS resolvers found at
> container start (#2970)

This feature automatically discovers cluster DNS (CoreDNS) at startup, eliminating the need to
disable the firewall for DNS resolution to work.

### New Configuration

```yaml
FIREWALL_INPUT_PORTS: 8080
FIREWALL_OUTBOUND_SUBNETS: 10.42.0.0/16,10.43.0.0/16
FIREWALL_VPN_INPUT_PORTS: ""
```

- Removed `FIREWALL: "off"` (defaults to on)
- Set correct pod CIDR (`10.42.0.0/16`) and service CIDR (`10.43.0.0/16`)

## Consequences

### Positive

- **Kill switch protection**: If VPN disconnects, all traffic is blocked (no leaks)
- **Correct cluster routing**: Traffic to pods and services routes correctly
- **Automatic DNS discovery**: Cluster DNS works without manual configuration

### Negative

- **Potential startup issues**: If gluetun fails to discover DNS, the pod may not start correctly
- **Debugging complexity**: Firewall-related issues are harder to diagnose than open networking

### Risks and Mitigation

If issues arise after enabling the firewall:

1. Check gluetun logs for DNS discovery: `kubectl logs -n media deploy/qbittorrent -c gluetun`
2. Temporarily revert by adding `FIREWALL: "off"` while investigating
3. Verify cluster CIDRs match `talos/talconfig.yaml`

## References

- [Gluetun v3.41.0 Release Notes][v3.41.0]
- [Gluetun v3.40.0 Release Notes][v3.40.0]
- [Gluetun Wiki: Firewall Options][firewall-wiki]
- [GitHub Issue #254: Kubernetes sidecar firewall issues][issue-254]

[v3.41.0]: https://github.com/qdm12/gluetun/releases/tag/v3.41.0
[v3.40.0]: https://github.com/qdm12/gluetun/releases/tag/v3.40.0
[firewall-wiki]: https://github.com/qdm12/gluetun-wiki/blob/main/setup/options/firewall.md
