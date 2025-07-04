# Claude Directives

This file provides guidance to Claude Code (claude.ai/code) when working with code in this
repository.

## Claude Directives

Claude MUST follow these directives when working in this repository:

### Teaching Protocol

Claude MUST always take a teaching approach, explain concepts and technical details, never assume
user knowledge level, provide context for technical concepts, stop and explain before complex
operations, define technical terms when first using them, and provide examples when explaining
abstract concepts or commands.

### Documentation Protocol

Claude MUST update memory bank at significant milestones and important decisions, reference
specific files and line numbers when discussing code (e.g., `file.yaml:123`), explain the "why"
not just the "what" when making recommendations, and document assumptions while verifying them
when possible.

### Operational Protocol

Claude MUST ask for confirmation before making significant changes or running potentially
disruptive commands, verify understanding by asking clarifying questions when instructions are
ambiguous, provide step-by-step explanations for multi-part processes, and explain expected
outcomes before executing commands.

### MCP Server Protocol

Claude MUST always prioritize MCP servers over CLI commands for Kubernetes operations, attempt
MCP operation 3 times before falling back to CLI, self-diagnose failures by checking tool usage
and parameters before declaring MCP failure, use granular fallback for specific failing
operations while continuing MCP for other functions, utilize flux-server for Flux operations and
k8s-server for Kubernetes operations, and continue using CLI for Talos operations, bootstrap
scripts, and template operations.

### Task Command Protocol

Claude MUST prioritize task commands over direct CLI operations when available, check
Taskfile.yaml and included task files for relevant tasks before running commands directly, and
explain task purpose and parameters when using task commands.

### Flux Configuration Protocol

Claude MUST always use `flux-system` as the GitRepository name in all Kustomization sourceRef
configurations, never use `home-kubernetes` or other names, follow the established repository
pattern where all ks.yaml files reference the same GitRepository resource, and verify sourceRef
matches existing Kustomizations when creating new Flux resources.

### Documentation Protocol Extended

Claude MUST always check documentation, README files, and existing configuration examples before
experimenting with commands or configurations, verify syntax and options through official
documentation when available, and ask for clarification rather than guessing when documentation
is unclear or unavailable.

### Hardware Configuration Protocol

Claude MUST always use diskSelector and similar hardware selectors when configuring Talos or
other hardware-related tasks, never assume generic device paths or names, reference the specific
hardware identifiers documented in the Node Details section, and verify hardware selectors
through talhelper or direct configuration validation.

### Talos Hardware Inspection Protocol

Claude MUST use talosctl commands to inspect actual hardware before configuring storage systems
like Rook Ceph, use stable device identifiers from `/dev/disk/by-id/` paths instead of volatile
device paths like `/dev/sdb`, verify device models and serial numbers match configuration, and
enable cleanup options for devices from previous installations when necessary.

#### Hardware Discovery Commands

```bash
# List all storage devices on a node
talosctl get disks -n <node-ip>

# Get detailed hardware information for specific device
talosctl get disk <device-name> -o yaml -n <node-ip>

# List stable device identifiers
talosctl list /dev/disk/by-id --long -n <node-ip>
```

#### Stable Device Identifier Priority

1. **Primary**: `/dev/disk/by-id/ata-*` or `/dev/disk/by-id/nvme-*` paths
2. **Secondary**: WWN identifiers (`wwn-0x*`)
3. **VM environments**: SCSI identifiers (`scsi-*`) for virtual disks
4. **Last resort**: Device model + serial number combination

#### Rook Ceph Configuration Requirements

- Use `devices` array with stable `/dev/disk/by-id/` paths instead of `deviceFilter`
- Enable `wipeDevicesFromOtherClusters: true` to clean previous Ceph installations
- Verify device availability and avoid OS disks (typically `/dev/sda` or `/dev/nvme0n1`)
- Target secondary storage devices that are dedicated for Ceph usage

### Helm Chart Deployment Protocol

Claude MUST research Helm chart structure before implementation, examine official chart
values.yaml for default configurations and potential conflicts, analyze all existing repository
HelmRelease patterns before choosing an approach, start with minimal configuration and add
complexity incrementally, use `helm template` or `helm show values` to validate configuration
before deployment, check official documentation and community issues for known configuration
conflicts, and test operator components separately from application components when deploying
complex systems.

### NFS Storage Protocol

Claude MUST use static PersistentVolumes for existing NFS data to preserve existing content,
create PersistentVolumeClaims within individual application directories following repository
patterns, use subPath mounting to provide granular access to NFS subdirectories, configure
app-specific access modes (ReadOnlyMany for read-only services like Plex, ReadWriteMany for
services requiring write access like Sonarr), and reference the static PVs in
`kubernetes/apps/nfs/` when creating application-specific PVCs.

### Kubernetes Application Structure Protocol

Claude MUST follow the cluster-template's directory structure conventions derived from GitOps best practices and ensure applications follow consistent deployment patterns.

#### Directory Structure Requirements

Claude MUST follow the strict convention where each top-level directory under `kubernetes/apps/` IS a Kubernetes namespace, ensure directory names MUST exactly match namespace names (e.g., `cert-manager/` → `namespace: cert-manager`, `network/` → `namespace: network`), verify the `kustomization.yaml` in each directory sets the matching target namespace, follow the established pattern: `apps/{namespace}/{service}/ks.yaml` and `apps/{namespace}/{service}/app/`, never create grouped directories that don't map to namespaces (violates template convention), and reference this when creating new applications: cert-manager, default, flux-system, kube-system, network, rook-ceph, nfs are the current namespace directories.

#### Single vs Multiple Kustomization Decision Matrix

Claude MUST use the following objective criteria to determine application structure:

**Single ks.yaml with multiple Kustomizations when ALL conditions are met:**
- Components deploy to the **same namespace**
- **Similar deployment timing** (both fast <5min or both slow >5min)  
- **Tightly coupled lifecycle** (upgraded/maintained together)
- **Simple dependency chain** (A enables B, no complex interdependencies)

**Multiple ks.yaml files in separate directories when ANY condition is met:**
- **Different namespaces** for related components
- **Dramatically different deployment timing** (seconds vs minutes)
- **Independent operational lifecycle** (can be upgraded separately)
- **Operator + Instance pattern** (software installation + configuration)
- **Complex dependency chains** (multiple external dependencies)

#### Deployment Timing Guidelines

Claude MUST apply appropriate timeout values based on deployment complexity:
- **Fast deployments** (<5 minutes): Standard Kubernetes manifests, simple Helm charts, configuration-only changes - Default timeout: 5m
- **Slow deployments** (>5 minutes): Complex distributed systems, storage provisioning, cluster-wide operators requiring initialization - Minimum timeout: 15m, adjust based on complexity

#### Health Check Standards

Claude MUST implement health checks appropriate to deployment complexity:
- **Simple**: HelmRelease health checks for standard applications
- **Complex**: Custom resource health checks with healthCheckExprs for operators and distributed systems that have specialized status conditions

#### Application Pattern Categories

Claude MUST apply these general patterns when implementing new applications:
- **Operator-based systems**: Multiple ks.yaml when operator installation is fast but resource provisioning is slow
- **Configuration-driven systems**: Single ks.yaml when extensions are configuration-only with same lifecycle
- **Dashboard/UI systems**: Single ks.yaml when UI components are configuration-only with same lifecycle  
- **Policy-based systems**: Multiple ks.yaml when policies have different lifecycles and external dependencies

#### Decision Process

Claude MUST follow this step-by-step evaluation for any new application:
1. **Evaluate complexity**: Does this require an operator + instance pattern? → Yes: Multiple ks.yaml
2. **Evaluate timing**: Do components have dramatically different deployment times? → Yes: Multiple ks.yaml  
3. **Evaluate lifecycle**: Will components be upgraded/maintained independently? → Yes: Multiple ks.yaml
4. **Evaluate dependencies**: Are there complex external dependencies for different components? → Yes: Consider multiple ks.yaml, No: Single ks.yaml appropriate

## Repository Overview

This is a **deployed and operational** Talos Kubernetes cluster with Flux GitOps. The cluster was
deployed using a template system (now archived) and is currently managed through direct
configuration files and operational tasks.

## Core Architecture

- **Operating System**: Talos Linux - Minimal, secure OS designed for Kubernetes
- **GitOps**: Flux v2 - Manages cluster state from Git repository
- **Secret Management**: SOPS with Age encryption for secrets
- **Storage**: Rook Ceph for application data, NFS for existing media from Unraid
- **Task Runner**: Taskfile (task) - All automation handled through tasks
- **Package Management**: mise - Manages CLI tool versions
- **Configuration**: talhelper - Manages Talos configuration generation

## Current Operations (Post-Cleanup)

### Environment Setup

```bash
# Install required CLI tools
mise trust && mise install

# Force Flux to sync repository changes
task reconcile
```

### Talos Operations

```bash
# Generate new Talos configuration
task talos:generate-config

# Apply config to specific node (IP and MODE required)
task talos:apply-node IP=192.168.1.50 MODE=auto

# Upgrade Talos on single node
task talos:upgrade-node IP=192.168.1.50

# Upgrade Kubernetes version
task talos:upgrade-k8s

# Reset cluster nodes to maintenance mode
task talos:reset
```

## Key Configuration Files

- `talos/talconfig.yaml` - Current Talos cluster configuration
- `Taskfile.yaml` - Main task definitions with includes
- `.mise.toml` - CLI tool version management
- `age.key` - SOPS encryption key (excluded from Git)
- `kubeconfig` - Kubernetes cluster access credentials

## Secret Management

- All secrets use SOPS encryption with Age keys
- Secret files follow pattern `*.sops.*`
- Age key stored in `age.key` (excluded from Git)
- SOPS configuration in `.sops.yaml`

## Directory Structure

- `kubernetes/` - Kubernetes manifests (Git-tracked)
- `talos/` - Talos configurations (Git-tracked)
- `bootstrap/` - Bootstrap configurations (Git-tracked)
- `scripts/` - Shell scripts for cluster operations
- `.private/` - Private files (Git-ignored, includes archived template files)

## GitOps Workflow

1. Modify Kubernetes manifests in `kubernetes/` directory
2. Commit and push changes to Git
3. Flux automatically applies changes to cluster
4. Use `task reconcile` to force immediate sync

## My Cluster Configuration

This section documents the specific configuration and setup details for this deployment.

### Network Configuration

- **Network**: 192.168.1.0/24
- **Gateway**: 192.168.1.1
- **Cluster API**: 192.168.1.70
- **DNS Gateway**: 192.168.1.71 (k8s_gateway)
- **Internal Gateway**: 192.168.1.72 (for internal services)
- **External Gateway**: 192.168.1.73 (for external/public services)

### Node Details

- **rias**: 192.168.1.61 - VM on lucy/Proxmox, MAC: bc:24:11:a7:98:2d
  - OS Disk: `/dev/sda` - QEMU HARDDISK (215GB) - `scsi-0QEMU_QEMU_HARDDISK_drive-scsi0`
  - Ceph Disk: `/dev/sdb` - QEMU HARDDISK (2TB) - `scsi-0QEMU_QEMU_HARDDISK_drive-scsi2`
- **nami**: 192.168.1.50 - Intel NUC, MAC: 94:c6:91:a1:e5:e8
  - OS Disk: `/dev/sda` - CT500MX500SSD4 (500GB) - `ata-CT500MX500SSD4_1824E1436952`
  - Ceph Disk: `/dev/sdb` - CT2000BX500SSD1 (2TB) - `ata-CT2000BX500SSD1_2513E9B2B5A5`
- **marin**: 192.168.1.59 - Intel NUC, MAC: 1c:69:7a:0d:8d:99
  - OS Disk: `/dev/sdb` - Samsung SSD 870 EVO 250GB - `ata-Samsung_SSD_870_EVO_250GB_S6PDNZ0R819892L`
  - Ceph Disk: `/dev/nvme0n1` - Samsung SSD 970 EVO Plus 1TB - `nvme-Samsung_SSD_970_EVO_Plus_1TB_S6S1NJ0TB03807K`
- All nodes configured as controllers for 3-node HA control plane

### Domain and External Access

- **Domain**: <domain>
- **Cloudflare Tunnel ID**: 6b689c5b-81a9-468e-9019-5892b3390500
- **Tunnel Target**: external.<domain> → 192.168.1.73
- **DNS Management**: external-dns automatically creates DNS records for new services

### Migration Context

- **Legacy System**: SWAG reverse proxy on Nezuko (192.168.1.58)
- **Legacy Path**: *.<domain> → WAN IP (99.61.133.53) → UDMP → Nezuko:30443
- **New Path**: Specific subdomains → Cloudflare tunnel → 192.168.1.73
- **Current State**: Parallel operation - new K8s services get tunnel routing, existing SWAG
  services continue via wildcard DNS

### Key Files (Local Only)

- `age.key` - SOPS encryption key (synced with Bitwarden)
- `cloudflare-tunnel.json` - Tunnel credentials
- `kubeconfig` - Kubernetes cluster access credentials
- `talos/clusterconfig/talosconfig` - Talos cluster access credentials

### Storage Infrastructure

- **Rook Ceph**: Distributed storage across all 3 nodes for application data and configuration
- **NFS Storage**: Static PersistentVolumes for existing Unraid data
  - **Server**: Nezuko (192.168.1.58)
  - **Media PV**: `/mnt/user/media` (movies, TV, music) - 100Ti
  - **Photos PV**: `/mnt/user/photos` (Immich photos) - 10Ti  
  - **FileRun PV**: `/mnt/user/filerun` (cloud storage) - 5Ti
  - **Access Pattern**: Apps create specific PVCs with subPath mounting
  - **Security**: NFSv4.1 with Private security for local network access

### Legacy Infrastructure

- **Docker Setup**: All services mounted at `/mnt/fast/docker/`
- **SWAG Location**: `/mnt/fast/docker/swag/`
- **Active SWAG Services**: adguard.subdomain.conf, homeassistant.subdomain.conf
- **Port Mapping**: SWAG uses ports 30080:80 and 30443:443

## Service Migration Learning & Workflow

This section documents key learnings about migrating services from SWAG to Kubernetes.

### DNS Record Management

- **external-dns**: Automatically creates Cloudflare DNS records for HTTPRoutes using `external`
  gateway
- **DNS precedence**: Specific records (echo.<domain>) override wildcard (*.<domain>)
- **TXT records**: Track which DNS records external-dns created (k8s.subdomain.domain.app)
- **Parallel operation**: New K8s services get tunnel routing, existing SWAG services continue via
  wildcard

### Application Deployment Patterns

- **HelmRelease**: Use when good Helm charts exist (Plex, Sonarr, etc.)
- **Plain YAML**: Use for simple apps or when you need full control
- **Template system**: `${SECRET_DOMAIN}` resolves to <domain> from cluster-secrets
- **Gateway routing**: `parentRefs: external` creates public DNS, `internal` for local-only

### Migration Testing Strategies

- **Branch testing**: Test in feature branches (Flux ignores non-main branches)
- **Namespace separation**: Deploy in `testing` namespace with different subdomain first
- **Internal-first**: Test with `internal` gateway before switching to `external`
- **Risk**: DNS records are created immediately when merged to main

### Key Tools and Commands

- **talhelper**: Manages Talos configuration, abstracts complex talosctl commands
- **external-dns**: Watches HTTPRoutes, creates DNS records automatically
- **cert-manager**: Provides end-to-end TLS (Cloudflare → cluster encryption)
- **flux-webhook**: Enables immediate Git sync instead of periodic polling

### Post-Template Cleanup

- **task template:tidy**: Moves template files to `.private/[timestamp]/` (doesn't delete)
- **Node management**: Can edit `talos/talconfig.yaml` directly after cleanup
- **Portability**: Only need `age.key` - everything else regenerates from Git

### Multi-Machine Workflow

- **Zero file transfer**: Clone repo + age.key from Bitwarden + `task talos:generate-config`
- **Config recreation**: `talhelper gencommand kubeconfig` rebuilds access credentials
- **Tool management**: `mise trust && mise install` handles all CLI dependencies

### Flux Configuration

- **Branch watching**: Only watches `main` branch (configured in GitRepository)
- **Sync interval**: 1 minute polling + immediate webhook sync
- **Secret management**: All secrets encrypted with Age, stored in Git
- **Automatic deployment**: Changes to main branch deploy immediately

## Initial Deployment (Historical - 2025-06-29)

This section documents the original template-based deployment process for reference and disaster
recovery purposes. These files and commands are no longer active but provide crucial context.

### Template System (Archived)

The cluster was originally deployed using a sophisticated template system:

- **Input Templates**: Located in `templates/` directory with `.j2` extension
- **Configuration Data**: Read from `cluster.yaml` and `nodes.yaml`
- **Output Generation**: Templates rendered to root directory and subdirectories
- **Custom Delimiters**: Used `#{variable}#` syntax instead of standard Jinja2

### Original Deployment Commands (Historical)

```bash
# Initialize configuration files from samples
task init

# Template out configurations (run after editing cluster.yaml/nodes.yaml)
task configure

# Bootstrap Talos Linux on nodes
task bootstrap:talos

# Bootstrap applications (flux, cilium, etc.)
task bootstrap:apps

# Clean up repository after initial setup
task template:tidy
```

### Original Configuration Files (Archived)

- `cluster.yaml` - Primary cluster configuration (contained Cloudflare API token, network config)
- `nodes.yaml` - Node-specific configuration (contained MAC addresses, node details)
- `makejinja.toml` - Template rendering configuration
- `templates/` - Jinja2 templates for all configurations

### Template Cleanup Process

After successful deployment, `task template:tidy` moved all template files to
`.private/[timestamp]/` directory, transitioning the repository from deployment mode to
operational mode.

## Important Notes

- All operations should use the task runner - avoid running commands directly
- SOPS-encrypted files should never be committed unencrypted
- Cloudflare integration is required for external access
- External-DNS automatically manages DNS records for new Kubernetes services
- Migration strategy allows parallel operation of SWAG and Kubernetes systems
- Node management uses `talos/talconfig.yaml` directly after template cleanup
