# Enable Gluetun Firewall with Kubernetes-Native DNS Discovery

- **Status:** Accepted
- **Date:** 2026-01-01
- **Decision:** Enable gluetun firewall using v3.41.0's automatic cluster DNS discovery

## Context and Problem Statement

The qbittorrent application uses gluetun as a VPN sidecar to route torrent traffic through ProtonVPN.
The firewall was disabled (`FIREWALL: "off"`) as a workaround for Kubernetes networking issues,
leaving no kill switch protection - if the VPN disconnects, traffic leaks unprotected to the
internet. Additionally, the configured subnets were incorrect defaults rather than actual cluster
CIDRs.

## Considered Options

- **Keep firewall disabled** - Maintains current behavior, no kill switch protection
- **Enable firewall with manual DNS configuration** - Complex, requires hardcoding CoreDNS IPs
- **Enable firewall with v3.41.0 automatic DNS discovery** - Leverages new Kubernetes-native support

## Decision Outcome

Chosen option: **Enable firewall with v3.41.0 automatic DNS discovery**, because gluetun v3.41.0
(released 2025-12-25) introduced automatic cluster DNS discovery at container startup, eliminating
the root cause of why the firewall was originally disabled.

New configuration:

```yaml
FIREWALL_INPUT_PORTS: 8080
FIREWALL_OUTBOUND_SUBNETS: 10.42.0.0/16,10.43.0.0/16
FIREWALL_VPN_INPUT_PORTS: ""
```

## Consequences

- Good, because kill switch protection prevents traffic leaks if VPN disconnects
- Good, because correct cluster CIDRs (pod: `10.42.0.0/16`, service: `10.43.0.0/16`) enable proper
  routing
- Good, because automatic DNS discovery eliminates manual CoreDNS configuration
- Bad, because firewall-related issues are harder to diagnose than open networking
- Bad, because if gluetun fails to discover DNS, the pod may not start correctly

If issues arise: check gluetun logs (`kubectl logs -n media deploy/qbittorrent -c gluetun`),
temporarily revert with `FIREWALL: "off"`, or verify CIDRs match `talos/talconfig.yaml`.

## References

- [Gluetun v3.41.0 Release Notes][v3.41.0]
- [Gluetun Wiki: Firewall Options][firewall-wiki]
- [GitHub Issue #254: Kubernetes sidecar firewall issues][issue-254]
- [GitHub Discussion #2340: Enabling firewall disables access][discussion-2340]

[v3.41.0]: https://github.com/qdm12/gluetun/releases/tag/v3.41.0
[firewall-wiki]: https://github.com/qdm12/gluetun-wiki/blob/main/setup/options/firewall.md
[issue-254]: https://github.com/qdm12/gluetun/issues/254
[discussion-2340]: https://github.com/qdm12/gluetun/discussions/2340

## Historical Context

The firewall was disabled from the initial qbittorrent deployment (commit fcb78882) due to known
issues with gluetun's firewall blocking cluster traffic in Kubernetes environments. The original
configuration used incorrect subnet values (`10.96.0.0/12`, `10.244.0.0/16`) which are
kubeadm/flannel defaults, not the actual Talos cluster CIDRs.
