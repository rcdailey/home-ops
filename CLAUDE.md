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
- MCP Servers: Prioritize MCP over CLI for Kubernetes operations
- Favor defaults over being unnecessarily explicit in configuration: this yields cleaner, less
  verbose, easier to maintain YAML

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
- Stop and wait for the user to commit & push changes after modifications are made and before
  checking cluster status.
- Don't perform reconcilation manually unless necessary.
- Always use `pre-commit run` to verify changes.
- Never specify explicit timeouts, intervals, or other timing related settings unless there's an
  explicit reason for them to solve an issue.

## Infrastructure & Storage Protocols

Claude MUST:

- NFS Storage: Use static PVs for existing data, create PVCs in app directories, use subPath
  mounting, configure appropriate access modes
- Database Isolation: Never share databases between applications, deploy dedicated instances,
  maintain independent isolation
- Secret Management: Keep secrets isolated per application, use centralized only for truly shared
  config, use `sops unset` for removal, use `sops --set` for modification
- Secret Integration Methods (priority order): 1) `envFrom` at app layer, 2) `env.valueFrom` for
  specific values, 3) HelmRelease `valuesFrom` for Helm chart values, 4) Flux variable substitution
  with `postBuild.substituteFrom` as last resort
- Helm Chart Analysis: Always run `helm show values <chart-name>/<chart> --version <version>` to
  check for `envFrom`, `env`, or other secret integration capabilities before choosing method

## Network & Access Protocols

Claude MUST:

- HTTPRoute Preference: Always favor HTTPRoute over Ingress and route through existing gateways.
- LoadBalancer Restrictions: NEVER create LoadBalancer services without explicit user discussion,
  reserve for core infrastructure requiring direct network access
- Gateway IP Assignment: Use externalIPs approach for Envoy Gateway services (192.168.1.72 internal,
  192.168.1.73 external) rather than LoadBalancer + IPAM for predictable, simple IP management
- NEVER use executable commands for health probes.
- External-DNS Architecture: Configure target annotations on Gateways only, never on HTTPRoutes. Use
  gateway-httproute source exclusively. This ensures CNAME-only records via inheritance and prevents
  A record fallbacks to LoadBalancer IPs.
- App-Template Route Priority: Always use app-template `route` field over standalone HTTPRoute when
  application uses app-template. Only use standalone HTTPRoute for external charts or
  operator-managed resources. Co-locate routing configuration with application configuration.
- Use the shortest resolvable hostname for Kubernetes services based on namespace scope. Do not use
  fully qualified domain names (FQDNs) when shorter forms will resolve correctly.

## Repository Overview

Operational Talos Kubernetes cluster with Flux GitOps. Core stack: Talos Linux, Flux v2, SOPS/Age
encryption, Rook Ceph + NFS storage, Taskfile automation, mise package management, talhelper
configuration.

## Operations

- **Setup**: `mise trust && mise install`
- **Sync**: `task reconcile`
- **Node config**: `task talos:apply-node IP=192.168.1.50 MODE=auto`
- **Upgrades**: `task talos:upgrade-node IP=192.168.1.50`
- **Image changes**: `talosctl upgrade --image` (apply-config only updates config, not running
  image)

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
- DNS Gateway: `192.168.1.71` (Technitium DNS)
- Internal Gateway: `192.168.1.72` (Envoy Gateway - LAN services)
- External Gateway: `192.168.1.73` (Envoy Gateway - WAN services)
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

## Important Notes

- SOPS-encrypted files must never be committed unencrypted
- External-DNS auto-manages DNS records for new services
- Migration allows parallel SWAG/Kubernetes operation
- Node management via `talos/talconfig.yaml` post-cleanup

## How to use tools

- For app-scout: @scripts/app-scout/README.md

### SOPS Commands

#### Set values in encrypted files

```bash
# Syntax: sops set file index value
sops set secret.sops.yaml '["stringData"]["KEY_NAME"]' '"value"'

# Examples:
sops set secret.sops.yaml '["stringData"]["API_KEY"]' '"abc123"'
sops set secret.sops.yaml '["stringData"]["WIREGUARD_PRIVATE_KEY"]' '"wOEI9rqq..."'
```

#### Remove values from encrypted files

```bash
# Syntax: sops unset file index
sops unset secret.sops.yaml '["stringData"]["KEY_NAME"]'

# Examples:
sops unset secret.sops.yaml '["stringData"]["MULLVAD_ACCOUNT"]'
sops unset secret.sops.yaml '["stringData"]["OLD_API_KEY"]'
```

#### Key points

- Index format: `'["section"]["key"]'` for YAML files
- Values must be JSON-encoded strings
- Always use single quotes around index path
- Use `--idempotent` flag to avoid errors if key exists/doesn't exist
