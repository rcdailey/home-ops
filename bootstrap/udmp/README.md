# UDMP BGP Configuration

BGP configuration for Cilium LB-IPAM integration with UniFi Dream Machine Pro.

## Configuration Details

- **UDMP ASN**: 64513
- **Kubernetes ASN**: 64514
- **BGP Router ID**: 192.168.1.1 (UDMP)
- **Peer Group**: k8s
- **Timers**: 15s keepalive, 45s hold time

## Peers

Control plane nodes:

- rias: 192.168.1.61
- nami: 192.168.1.50
- marin: 192.168.1.59

Worker nodes:

- sakura: 192.168.1.62
- hanekawa: 192.168.1.63

## Apply Configuration

1. Navigate to UniFi UI: <https://unifi.ui.com>
2. Go to **Network** → **Settings** → **Policy Engine** → **BGP**
3. Click **Upload Configuration**
4. Select `bgp.conf` from this directory
5. Click **Apply Changes**

## Verification

After applying:

- BGP neighbors will show "Idle" until Cilium BGP is configured
- Once Cilium is configured, neighbors should transition to "Established"
- Check status in UniFi UI under Network → Insights → BGP

## Requirements

- UniFi OS version 4.1.13 or newer (UDMP, UDMP-SE, or UDM-Pro-Max)
- Cilium with BGP control plane enabled (see `kubernetes/apps/kube-system/cilium/`)

## Related Documentation

- [Cilium BGP Control Plane](https://docs.cilium.io/en/stable/network/bgp-control-plane/)
- [UniFi BGP Documentation](https://help.ui.com/hc/en-us/articles/16271338193559)
