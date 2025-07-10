# Claude Directives

## Core Operational Protocols

Claude MUST:

- Teaching: Always explain concepts, define terms, provide context, and give examples when
  explaining technical concepts
- Documentation: Update memory bank at milestones, reference files with line numbers
  (`file.yaml:123`), explain "why" not just "what", verify assumptions
- Operations: Ask confirmation before disruptive commands, provide step-by-step explanations,
  explain expected outcomes
- Git: NEVER run `git commit`/`git push` without explicit user request, GitOps requires user to
  commit/push (not Claude). Stop and wait for the user to do this before running commands like
  reconcile.
- Task Commands: Prioritize task commands over direct CLI, check Taskfile.yaml first, explain task
  purpose
- MCP Servers: Prioritize MCP over CLI for Kubernetes operations, attempt 3x before CLI fallback,
  use flux-server/k8s-server

## Development & Deployment Protocols

Claude MUST:

- Validation Sequence: kustomize build → kubectl dry-run (server) → flux check, use server-side
  dry-run, validate dependencies
- Flux Configuration: Always use `flux-system` as GitRepository name, verify sourceRef matches
  existing Kustomizations
- Helm Management: Check latest versions with `helm search repo <chart> --versions`, use `helm
  template` for validation, co-locate HelmRepository with single-use charts, use two-Kustomization
  approach for secrets with postBuild substitution
- App-Template: Use centralized bjw-s OCIRepository, reference with `chartRef: {kind: OCIRepository,
  name: app-template}`, use HTTPRoute not ingress, add `postBuild.substituteFrom` with
  `cluster-secrets`
- Directory Structure: Each `kubernetes/apps/` directory IS a namespace, directory names MUST match
  namespace names exactly
- Application Structure Decision: Single ks.yaml when same namespace + similar timing + coupled
  lifecycle. Multiple ks.yaml when different namespaces OR different timing OR independent lifecycle
  OR operator+instance pattern
- Deployment Timing: Fast (<5min) = 5m timeout, Slow (>5min) = 15m+ timeout based on complexity

## Infrastructure & Storage Protocols

Claude MUST:

- Hardware Configuration: Always use diskSelector, reference Node Details section hardware
  identifiers, verify through talhelper
- Talos Hardware: Use `talosctl get disks -n <ip>` to inspect hardware, use stable
  `/dev/disk/by-id/` paths, enable cleanup for previous installations
- Stable Device Priority: 1) `/dev/disk/by-id/ata-*` or `nvme-*`, 2) WWN identifiers, 3) SCSI for
  VMs, 4) Model+serial
- Rook Ceph: Use `devices` array with stable paths, enable `wipeDevicesFromOtherClusters: true`,
  avoid OS disks
- NFS Storage: Use static PVs for existing data, create PVCs in app directories, use subPath
  mounting, configure appropriate access modes
- Database Isolation: Never share databases between applications, deploy dedicated instances,
  maintain independent isolation
- Secret Management: Keep secrets isolated per application, use centralized only for truly shared
  config, use `sops unset` for removal, use `sops --set` for modification

## Network & Access Protocols

Claude MUST:

- HTTPRoute Preference: Always favor HTTPRoute over Ingress, route through existing gateways, use
  ClusterIP services with HTTPRoute
- LoadBalancer Restrictions: NEVER create LoadBalancer services without explicit user discussion,
  reserve for core infrastructure requiring direct network access
- VIP Allocation: ONLY k8s-gateway (192.168.1.71), internal gateway (192.168.1.72), external gateway
  (192.168.1.73), rare infrastructure exceptions
- LoadBalancer Decision Matrix: Create ONLY when ALL criteria met: Infrastructure component +
  Non-HTTP protocol + Direct access required + No HTTPRoute alternative
- VIP Testing: Use service-specific ports not ping, test with `dig @192.168.1.71` for DNS, `curl -I
  http://192.168.1.72` for gateways

## Repository Overview

Operational Talos Kubernetes cluster with Flux GitOps. Core stack: Talos Linux, Flux v2, SOPS/Age
encryption, Rook Ceph + NFS storage, Taskfile automation, mise package management, talhelper
configuration.

## Operations

```bash
# Setup: mise trust && mise install
# Sync: task reconcile
# Node config: task talos:apply-node IP=192.168.1.50 MODE=auto
# Upgrades: task talos:upgrade-node IP=192.168.1.50
```

## Key Files

- `talos/talconfig.yaml` - Talos cluster configuration
- `Taskfile.yaml` - Task definitions
- `age.key` - SOPS encryption key (local only)
- `kubeconfig` - Kubernetes access credentials

## GitOps Workflow

1. Modify manifests in `kubernetes/` directory
2. USER COMMITS/PUSHES (not Claude)
3. Flux auto-applies changes
4. Use `task reconcile` for immediate sync

## Cluster Configuration

### Network

- Network: `192.168.1.0/24`, Gateway: `192.168.1.1`, Cluster API: `192.168.1.70`
- DNS Gateway: `192.168.1.71` (k8s_gateway)
- Internal Gateway: `192.168.1.72` (LAN services)
- External Gateway: `192.168.1.73` (WAN services)
- Cloudflare Tunnel: `6b689c5b-81a9-468e-9019-5892b3390500` → `192.168.1.73`

### Node Details

- rias: `192.168.1.61` - VM/Proxmox, MAC: `bc:24:11:a7:98:2d`
  - OS: `/dev/sda` - `scsi-0QEMU_QEMU_HARDDISK_drive-scsi0`
  - Ceph: `/dev/sdb` - `scsi-0QEMU_QEMU_HARDDISK_drive-scsi2`
- nami: `192.168.1.50` - Intel NUC, MAC: `94:c6:91:a1:e5:e8`
  - OS: `/dev/sda` - `ata-CT500MX500SSD4_1824E1436952`
  - Ceph: `/dev/sdb` - `ata-CT2000BX500SSD1_2513E9B2B5A5`
- marin: `192.168.1.59` - Intel NUC, MAC: `1c:69:7a:0d:8d:99`
  - OS: `/dev/sdb` - `ata-Samsung_SSD_870_EVO_250GB_S6PDNZ0R819892L`
  - Ceph: `/dev/nvme0n1` - `nvme-Samsung_SSD_970_EVO_Plus_1TB_S6S1NJ0TB03807K`

### Storage

- Rook Ceph: Distributed storage across all 3 nodes
- NFS: Static PVs from Nezuko (`192.168.1.58`) - Media (100Ti), Photos (10Ti), FileRun (5Ti)
- Access: Apps create PVCs with subPath mounting, NFSv4.1 private security

### Core Infrastructure Namespaces

- `kube-system` - Kubernetes system components, Gateways (internal/external)
- `flux-system` - Flux GitOps controllers and configurations
- `network` - Network infrastructure (external-dns, cloudflare-dns)
- `rook-ceph` - Ceph storage system components
- `nfs` - NFS storage components
- `cert-manager` - Certificate management infrastructure

## Historical Deployment (2025-06-29)

Original template-based deployment using Jinja2 templates in `templates/` directory with
`cluster.yaml`/`nodes.yaml` configuration. Bootstrap sequence: `task init` → `task configure` →
`task bootstrap:talos` → `task bootstrap:apps` → `task template:tidy`. Templates archived to
`.private/[timestamp]/` directory post-deployment.

@MIGRATION.md

## Important Notes

- Use task runner for all operations
- SOPS-encrypted files must never be committed unencrypted
- Cloudflare integration required for external access
- External-DNS auto-manages DNS records for new services
- Migration allows parallel SWAG/Kubernetes operation
- Node management via `talos/talconfig.yaml` post-cleanup
- Never specify explicit timeouts, intervals, or other timing related settings unless there's an
  explicit reason for them to solve an issue.

## How to use tools

- For app-scout: @scripts/app-scout/README.md
