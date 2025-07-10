# Migration Documentation

This document contains migration-specific information for transitioning services from SWAG to
Kubernetes.

## Migration Context

- **Legacy System**: SWAG reverse proxy on Nezuko (192.168.1.58)
- **Legacy Path**: *.<domain> → WAN IP → UDMP → Nezuko:30443
- **New Path**: Specific subdomains → Cloudflare tunnel → 192.168.1.73
- **Current State**: Parallel operation - new K8s services get tunnel routing, existing SWAG
  services continue via wildcard DNS

## Legacy Infrastructure

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

### Multi-Machine Workflow

- **Zero file transfer**: Clone repo + age.key from Bitwarden + `task talos:generate-config`
- **Config recreation**: `talhelper gencommand kubeconfig` rebuilds access credentials
- **Tool management**: `mise trust && mise install` handles all CLI dependencies
- **Node management**: Direct editing of `talos/talconfig.yaml` in operational mode

### Flux Configuration

- **Branch watching**: Only watches `main` branch (configured in GitRepository)
- **Sync interval**: 1 minute polling + immediate webhook sync
- **Secret management**: All secrets encrypted with Age, stored in Git
- **Automatic deployment**: Changes to main branch deploy immediately
