# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@README.md

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

## Important Notes

- All operations should use the task runner - avoid running commands directly
- Template rendering must be done after any configuration changes
- SOPS-encrypted files should never be committed unencrypted
- The repository supports both bare-metal and VM deployments
- Cloudflare integration is required for external access
