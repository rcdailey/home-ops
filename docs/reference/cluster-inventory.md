# Cluster inventory

This document records current infrastructure facts used during diagnostics. Validate live state
before making a decision that depends on an address, device, or capacity.

## Stack

- Talos Linux and Kubernetes with Flux
- SOPS with Age and External Secrets Operator with Infisical
- Rook Ceph, NFS, Garage S3, and Volsync
- Just, mise, and talhelper

VMAlertmanager sends alerts through Pushover. The Watchdog alert pings Healthchecks.io every five
minutes so an external service detects a monitoring or cluster outage.

## Network

- Main subnet: `192.168.1.0/24`
- Cilium LoadBalancer subnet: `192.168.50.0/24`
- AT&T BGW320-505 gateway in IP passthrough mode
- UniFi gateway: `192.168.1.1`
- Kubernetes API: `192.168.1.70`
- Infrastructure LoadBalancers: `192.168.50.71-99`
- Application LoadBalancers: `192.168.50.100+`

## Nodes

| Node | Role | Address | System disk | Ceph disk |
| --- | --- | --- | --- | --- |
| hanekawa | Control plane | `192.168.1.63` | Intel S3700 400GB | 970 EVO Plus 1TB, OSD.5 |
| marin | Control plane | `192.168.1.59` | Intel S3700 400GB | 970 EVO Plus 1TB, OSD.2 |
| sakura | Control plane | `192.168.1.62` | Intel S3700 400GB | 970 EVO Plus 1TB, OSD.4 |
| lucy | Worker | `192.168.1.54` | Intel S3700 400GB | Crucial P3 2TB, OSD.3 |
| nami | Worker | `192.168.1.50` | Intel S3700 400GB | Samsung 990 PRO 2TB, OSD.0 |

Every node uses `sda` for Talos and `nvme0n1` for its Ceph OSD. Devices named `rbd*` are Ceph RBD
volumes mapped by CSI, not physical disks.

## Storage

- NFS host Nezuko: `192.168.1.58`, 100Ti media and 10Ti photos storage
- Garage S3: `192.168.1.58:3900`, region `garage`, with per-application buckets
- Volsync: shared Kopia repository at `/mnt/user/volsync` with snapshot identity isolation
- CloudNativePG: Barman WAL archives in per-application Garage buckets

See `docs/architecture/backup-strategy.md` for backup design and
`docs/runbooks/ceph-osd-operations.md` for Ceph procedures.
