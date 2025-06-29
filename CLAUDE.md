# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@README.md

## Claude Directives

Claude MUST follow these directives when working in this repository:

### Teaching Approach
- **ALWAYS take a teaching approach** - explain concepts, processes, and technical details
- **NEVER assume user knowledge level** - provide context and background for technical concepts
- **STOP and explain** before proceeding with complex operations or when introducing new concepts
- **Define technical terms** when first using them in conversation
- **Provide examples** when explaining abstract concepts or commands

### Documentation Standards
- **Update memory bank** at significant milestones and when important decisions are made
- **Reference specific files and line numbers** when discussing code (e.g., `file.yaml:123`)
- **Explain the "why" not just the "what"** when making recommendations
- **Document assumptions** and verify them when possible

### Operational Approach
- **Ask for confirmation** before making significant changes or running potentially disruptive commands
- **Verify understanding** by asking clarifying questions when instructions are ambiguous
- **Provide step-by-step explanations** for multi-part processes
- **Explain expected outcomes** before executing commands

## Repository Overview

This is a Kubernetes cluster template for deploying a single cluster using Talos Linux and Flux GitOps. The project uses makejinja for template rendering to generate cluster configurations from YAML configuration files.

## Core Architecture

- **Operating System**: Talos Linux - A minimal, secure OS designed for Kubernetes
- **GitOps**: Flux v2 - Manages cluster state from Git repository
- **Templating**: makejinja - Renders Jinja2 templates from cluster/node configuration
- **Secret Management**: SOPS with Age encryption for secrets
- **Task Runner**: Taskfile (task) - All automation is handled through tasks
- **Package Management**: mise - Manages CLI tool versions

## Essential Commands

### Development Environment Setup
```bash
# Install required CLI tools
mise trust
pip install pipx
mise install

# Initialize configuration files from samples
task init

# Template out configurations (run after editing cluster.yaml/nodes.yaml)
task configure
```

### Cluster Deployment
```bash
# Bootstrap Talos Linux on nodes
task bootstrap:talos

# Bootstrap applications (flux, cilium, etc.)
task bootstrap:apps

# Force Flux to sync repository changes
task reconcile
```

### Talos Operations
```bash
# Generate new Talos configuration
task talos:generate-config

# Apply config to specific node (IP and MODE required)
task talos:apply-node IP=10.0.0.10 MODE=auto

# Upgrade Talos on single node
task talos:upgrade-node IP=10.0.0.10

# Upgrade Kubernetes version
task talos:upgrade-k8s

# Reset cluster nodes to maintenance mode
task talos:reset
```

### Template Management
```bash
# Debug cluster resources (outputs to debug/ directory)
task template:debug

# Clean up repository after initial setup
task template:tidy
```

## Key Configuration Files

- `cluster.yaml` - Primary cluster configuration (created from cluster.sample.yaml)
- `nodes.yaml` - Node-specific configuration (created from nodes.sample.yaml)
- `makejinja.toml` - Template rendering configuration
- `Taskfile.yaml` - Main task definitions with includes from .taskfiles/
- `.mise.toml` - CLI tool version management

## Template System

The repository uses a sophisticated template system:

1. **Input Templates**: Located in `templates/` directory with `.j2` extension
2. **Configuration Data**: Read from `cluster.yaml` and `nodes.yaml`
3. **Output Generation**: Templates render to root directory and subdirectories
4. **Custom Delimiters**: Uses `#{variable}#` syntax instead of standard Jinja2

## Secret Management

- All secrets use SOPS encryption with Age keys
- Secret files follow pattern `*.sops.*`
- Age key stored in `age.key` (excluded from Git)
- SOPS configuration in `.sops.yaml`

## Directory Structure

- `templates/` - Jinja2 templates for all configurations
- `kubernetes/` - Generated Kubernetes manifests (Git-tracked)
- `talos/` - Generated Talos configurations (Git-tracked)
- `bootstrap/` - Generated bootstrap configurations (Git-tracked)
- `scripts/` - Shell scripts for cluster operations
- `.taskfiles/` - Modular task definitions
- `.private/` - Private files (Git-ignored)

## Validation and Linting

The template system includes comprehensive validation:
- **CUE schemas** for cluster/node configuration validation
- **kubeconform** for Kubernetes manifest validation
- **YAML linting** during template rendering

## GitOps Workflow

1. Modify `cluster.yaml` or `nodes.yaml` configurations
2. Run `task configure` to render templates
3. Commit and push changes to Git
4. Flux automatically applies changes to cluster
5. Use `task reconcile` to force immediate sync

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
- **rias**: 192.168.1.61 - VM on lucy/Proxmox, /dev/sda, MAC: bc:24:11:a7:98:2d
- **nami**: 192.168.1.50 - Intel NUC, /dev/sda, MAC: 94:c6:91:a1:e5:e8
- **marin**: 192.168.1.59 - Intel NUC, /dev/nvme0n1, MAC: 1c:69:7a:0d:8d:99
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
- **Current State**: Parallel operation - new K8s services get tunnel routing, existing SWAG services continue via wildcard DNS

### Key Files (Local Only)
- `cluster.yaml` - Contains Cloudflare API token, network configuration
- `nodes.yaml` - Contains MAC addresses, node-specific details
- `cloudflare-tunnel.json` - Tunnel credentials
- `age.key` - SOPS encryption key (synced with Bitwarden)

### Legacy Infrastructure
- **Docker Setup**: All services mounted at `/mnt/fast/docker/`
- **SWAG Location**: `/mnt/fast/docker/swag/`
- **Active SWAG Services**: adguard.subdomain.conf, homeassistant.subdomain.conf
- **Port Mapping**: SWAG uses ports 30080:80 and 30443:443

## Service Migration Learning & Workflow

This section documents key learnings about migrating services from SWAG to Kubernetes.

### DNS Record Management
- **external-dns**: Automatically creates Cloudflare DNS records for HTTPRoutes using `external` gateway
- **DNS precedence**: Specific records (echo.<domain>) override wildcard (*.<domain>) 
- **TXT records**: Track which DNS records external-dns created (k8s.subdomain.domain.app)
- **Parallel operation**: New K8s services get tunnel routing, existing SWAG services continue via wildcard

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

## Important Notes

- All operations should use the task runner - avoid running commands directly
- Template rendering must be done after any configuration changes to cluster.yaml/nodes.yaml
- SOPS-encrypted files should never be committed unencrypted
- The repository supports both bare-metal and VM deployments
- Cloudflare integration is required for external access
- External-DNS automatically manages DNS records for new Kubernetes services
- Migration strategy allows parallel operation of SWAG and Kubernetes systems
- Template cleanup via `task template:tidy` archives files but doesn't prevent future node management