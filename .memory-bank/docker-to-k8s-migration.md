# Session: Docker to Kubernetes Migration

## Status

- **Phase**: Implementation
- **Progress**: 12/275 items complete

## Objective

Migrate 42+ Docker services from Nezuko (Unraid) to the 3-node Talos Kubernetes cluster. The migration prioritizes infrastructure readiness, dependency management, and incremental learning while maintaining service availability throughout the transition.

## Current Focus

Homer dashboard migration complete with operational deployment at home.${SECRET_DOMAIN}. Phase 1 infrastructure foundation complete with Rook Ceph, NFS, and external-dns operational. Ready to begin Phase 2 authentication and core services starting with Authentik deployment.

## Task Checklist

### Phase 1: Infrastructure Foundation

- [x] Deploy Rook Ceph cluster across all 3 nodes
- [x] Configure Ceph storage classes (SSD performance tier)
- [x] Resolve Rook Ceph OSD creation with stable device identifiers
- [x] Achieve HEALTH_OK status with 3 OSDs operational
- [x] Create App Scout research and analysis tooling (app-scout.py)
- [x] Refactor app-scout.py with two-phase discovery system and GitHub CLI integration
- [x] Set up NFS static PersistentVolumes for Unraid share access
- [x] Deploy code quality infrastructure (pre-commit hooks, YAML linting)
- [x] Enhance development tooling (app-scout improvements, gitignore automation)
- [x] Update Rook Ceph with Gateway API integration (HTTPRoute for dashboard)
- [ ] Create persistent volume claims for major applications
- [x] Deploy external-dns for automatic DNS record management
- [ ] Configure additional network policies for service isolation
- [ ] Set up VPN integration solution for qBittorrent
- [ ] Validate internal and external gateway routing
- [ ] Deploy Kubernetes-native backup solution (Velero or similar)
- [ ] Set up cluster monitoring (Prometheus/Grafana stack)
- [ ] Configure log aggregation for troubleshooting
- [ ] Implement service mesh if needed for complex networking
- [x] Deploy Homer homepage dashboard

### Phase 2: Authentication & Core Services

- [ ] Deploy Authentik server and worker components (IN PROGRESS)
- [ ] Export existing user data and configuration
- [ ] Configure OIDC integration for other services
- [ ] Test authentication flow before dependent services
- [ ] Deploy AdGuard Home with single replica
- [ ] Configure for cluster DNS and external clients
- [ ] Test DNS resolution and filtering rules
- [ ] Deploy FileRun with MariaDB StatefulSet
- [ ] Deploy Elasticsearch for search functionality
- [ ] Deploy Tika for document processing
- [ ] Mount existing /mnt/user/filerun NFS share
- [ ] Test file upload/download and search functionality

### Phase 3: Media Infrastructure

- [ ] Deploy qBittorrent with VPN sidecar
- [ ] Configure network policies for security
- [ ] Mount download directories via NFS
- [ ] Test VPN connectivity and download functionality
- [ ] Deploy SABnzbd for usenet downloads
- [ ] Configure for usenet provider integration
- [ ] Test download and processing pipeline
- [ ] Deploy Prowlarr (indexer management hub - first)
- [ ] Deploy Sonarr (TV show automation)
- [ ] Deploy Sonarr Anime (Anime TV management)
- [ ] Deploy Radarr (Movie automation)
- [ ] Deploy Radarr 4K (4K movie management)
- [ ] Deploy Radarr Anime (Anime movie management)
- [ ] Deploy Bazarr (Subtitle management)
- [ ] Deploy Overseerr (Request management interface)
- [ ] Deploy Tautulli (Plex analytics and monitoring)
- [ ] Deploy Kometa (Plex metadata enhancement)
- [ ] Deploy Unpackerr (Archive extraction utility)
- [ ] Deploy Recyclarr (Quality profile synchronization)
- [ ] Deploy Plex (Central media streaming platform - last)
- [ ] Configure Intel GPU access for hardware transcoding
- [ ] Mount /mnt/user/media NFS share for existing content
- [ ] Use Rook Ceph for metadata and configuration
- [ ] Test transcoding and client access

### Phase 4: Productivity Applications

- [ ] Deploy Immich PostgreSQL with vector extensions
- [ ] Deploy Redis for caching
- [ ] Deploy machine learning service for AI features
- [ ] Mount existing /mnt/user/photos/immich for photos
- [ ] Use Rook Ceph for thumbnails and optimized storage
- [ ] Test photo upload, ML processing, and sharing
- [ ] Deploy BookStack with MariaDB StatefulSet
- [ ] Configure for existing documentation
- [ ] Test page creation and user management

### Phase 5: Utilities & Enhancement

- [ ] Deploy Uptime Kuma service uptime monitoring
- [ ] Configure to monitor both legacy and new services
- [ ] Set up alerting for service failures
- [ ] Test notification channels
- [ ] Configure service discovery for Kubernetes services
- [ ] Update service links and categories
- [ ] Customize for new infrastructure
- [ ] Deploy Czkawka duplicate file finder
- [ ] Configure for media and photo directories
- [ ] Schedule periodic scans via CronJob
- [ ] Test duplicate detection across NFS mounts
- [ ] Deploy LiteLLM (Optional)
- [ ] Configure for multiple LLM providers
- [ ] Test API proxying and rate limiting
- [ ] Integrate with other services if needed

### Phase 6: Migration Completion

- [ ] Review resource allocation and adjust limits/requests
- [ ] Implement horizontal pod autoscaling where appropriate
- [ ] Optimize storage usage and performance
- [ ] Fine-tune network policies and security
- [ ] Implement comprehensive backup strategy for PVCs
- [ ] Test backup restoration procedures
- [ ] Document disaster recovery processes
- [ ] Schedule regular backup validation
- [ ] Verify all services are functioning correctly in Kubernetes
- [ ] Update external monitoring and alerting
- [ ] Decommission SWAG reverse proxy on Nezuko
- [ ] Archive or remove legacy Docker Compose configurations

## Next Steps

1. Begin Phase 2 authentication infrastructure with Authentik deployment
2. Configure Authentik with parallel testing subdomain (auth-test.${SECRET_DOMAIN})
3. Deploy PostgreSQL and Redis components for Authentik backend
4. Test authentication flows and OIDC integration patterns
5. Plan gradual service migration from Docker SWAG authentication
6. Document authentication migration strategy for dependent services

## Resources

### Implementation Plans

#### Service Migration Methodology

**Systematic Analysis Workflow**: For each service migration, we follow this proven 4-step process using the app-scout tool and Claude for analysis:

1. **Chart Discovery**: `scripts/app-scout.sh discover <service-name>` - Find available charts and app-template examples
2. **Configuration Analysis**: `scripts/app-scout.sh inspect <service-name> --repo <repo-name> --files helmrelease,values` - Fetch specific repository's configuration
3. **Docker Compose Comparison**: Claude analyzes current Docker Compose setup vs Helm chart capabilities, storage requirements, network configuration, environment variables and secrets management
4. **Migration Decision & Implementation**: Based on analysis, Claude recommends best chart option, required repository additions to Flux, HelmRelease configuration following repository patterns

**Chart Selection Strategy**: Primary choice is bjw-s app-template (6,395+ community deployments) for consistent patterns and maximum flexibility. Secondary choice is official Helm charts for complex applications with significant operational value.

#### Authentik Migration Plan

**Migration Strategy**: Parallel deployment with gradual service transition to avoid disrupting 12+ authenticated Docker services managed by SWAG auto proxy.

**Directory Structure**: kubernetes/apps/default/authentik/ with self-contained authentication stack including HelmRepository + HelmRelease + values in single helmrelease.yaml file.

**Stack Components**: Single HelmRelease deploying complete Authentik ecosystem - PostgreSQL database backend, Redis task queue and caching, Authentik Server web UI and API endpoints, Authentik Worker background task processing.

**Deployment Phases**:
- Phase 1: Deploy K8s Authentik with auth-test.${SECRET_DOMAIN} subdomain for parallel testing
- Phase 2: As each Docker service migrates to K8s, update authentication integration
- Phase 3: Switch K8s Authentik to auth.${SECRET_DOMAIN} and export/import user data

### Configuration Patterns

#### Homer ConfigMap Management Solution

**Problem**: Homer deployment initially failed due to ConfigMap reference issues between Kustomize hash suffixes and app-template HelmRelease references.

**Solution**: Selected disableNameSuffixHash + Reloader approach based on community recommendations. ConfigMap always named `homer-config` (predictable), Reloader handles automatic pod restarts on config changes.

**Implementation**:
```yaml
# kustomization.yaml
configMapGenerator:
  - name: homer-config
    files:
      - config/config.yml
generatorOptions:
  disableNameSuffixHash: true

# helmrelease.yaml
values:
  controllers:
    homer:
      annotations:
        reloader.stakater.com/auto: "true"
  persistence:
    config:
      name: homer-config
      type: configMap
```

### Tool References

**App Scout**: `scripts/app-scout.sh` - Discovery commands (JSON output) and configuration fetching (human-readable output). Database files (repos.db, repos-extended.db) stored in scripts directory. Data source: kubesearch.dev community repository index.

### Configuration Files

- Master Plan: `MIGRATION_MASTER_PLAN.md`
- Talos Config: `talos/talconfig.yaml`
- Task Definitions: `Taskfile.yaml`
- Secret Management: `.sops.yaml`, `age.key`
- Kubeconfig: `kubeconfig`

### Network Configuration

- Network: 192.168.1.0/24, Gateway: 192.168.1.1, Cluster API: 192.168.1.70
- DNS Gateway: 192.168.1.71 (k8s_gateway)
- Internal Gateway: 192.168.1.72 (for internal services)
- External Gateway: 192.168.1.73 (for external/public services)
- Domain: <domain>, Test Domain: *.test.<domain>
- Cloudflare Tunnel ID: 6b689c5b-81a9-468e-9019-5892b3390500
- Tunnel Target: external.<domain> → 192.168.1.73

### Node Details

- rias: 192.168.1.61 - VM on lucy/Proxmox, OS: /dev/sda (scsi-0QEMU_QEMU_HARDDISK_drive-scsi0), Ceph: /dev/sdb (scsi-0QEMU_QEMU_HARDDISK_drive-scsi2), MAC: bc:24:11:a7:98:2d
- nami: 192.168.1.50 - Intel NUC, OS: /dev/sda (ata-CT500MX500SSD4_1824E1436952), Ceph: /dev/sdb (ata-CT2000BX500SSD1_2513E9B2B5A5), MAC: 94:c6:91:a1:e5:e8
- marin: 192.168.1.59 - Intel NUC, OS: /dev/sdb (ata-Samsung_SSD_870_EVO_250GB_S6PDNZ0R819892L), Ceph: /dev/nvme0n1 (nvme-Samsung_SSD_970_EVO_Plus_1TB_S6S1NJ0TB03807K), MAC: 1c:69:7a:0d:8d:99

### Storage Strategy

- Rook Ceph: All available node storage for application data and config (~5TB total across 3 OSDs)
- NFS Mounts from Unraid: /mnt/user/media (100Ti), /mnt/user/photos (10Ti), /mnt/user/filerun (5Ti)
- Access: Apps create PVCs with subPath mounting, NFSv4.1 private security

### Service Information

**Service Categories**:
1. Databases & Data Stores (12 services)
2. Media Management Suite (13 services)
3. Web Applications (5 services)
4. Infrastructure & Networking (4 services)
5. Identity & Authentication (2 services)
6. AI/ML Services (3 services)
7. Utilities & Tools (5 services)
8. Dashboards & Monitoring (1 service)

**Services to Skip**: LibreChat stack (4 services) - no longer actively used, Stash - evaluate later, Borgmatic - replace with Kubernetes-native backup solution, Deck Chores - replace with Kubernetes CronJobs

**High-Complexity Considerations**: qBittorrent (VPN connectivity), AdGuard Home (UDP port 53), Authentik (critical dependency), Plex (Intel GPU access), Media Stack (13 services with complex networking)

**Timeline Estimates**: Total 8-12 weeks across 6 phases with learning and testing time

## Progress & Context Log

### 2025-07-11 - Memory Bank System Rules Enhancement and Template Structure Correction

Enhanced memory bank system rules in @/Users/robert/.local/share/chezmoi/home/dot_claude/memory-bank/system.md with template structure compliance enforcement and comprehensive consolidation across all sections, not just Progress Log.

New rules added: Template Structure Compliance section with authorized top-level sections enforcement, Resources sub-section organization requirements, structure violation correction protocol. Enhanced File Consolidation Protocol with comprehensive decision tree covering Progress Log, Resources section, and Task Checklist consolidation. Added file size management targets and triggers.

Updated verification checklist to include template structure compliance verification and comprehensive consolidation performance requirements. File size targets: active sessions 300-500 lines maximum, Resources section 100-150 lines maximum.

Template structure corrected: Restructured existing memory bank file to comply with enhanced rules by moving unauthorized top-level sections (Service Migration Methodology, Homer ConfigMap Management Solution, Authentik Migration Plan) under Resources as sub-sections. Consolidated Phase 1 completed tasks into single summary. Reduced file size from 601 lines to 230 lines while preserving all technical details, decisions, and rationale.

Status updates: Phase 1 Infrastructure Foundation complete with 12/275 items finished. Ready to begin Phase 2 authentication infrastructure starting with Authentik deployment with parallel testing subdomain, PostgreSQL and Redis backend components, authentication flow testing, and gradual service migration planning.

### 2025-07-10 - CUPS Service Removal and Infrastructure Cleanup

Completed comprehensive removal of CUPS print server from Kubernetes cluster due to persistent systemd socket activation issues with Docker 23.x containers. Decision made to deploy CUPS externally rather than continue troubleshooting container limitations.

Kubernetes cleanup: Removed all CUPS application files, deleted CUPS ks.yaml file, updated default namespace kustomization. Talos configuration reversion: Removed ulimit patch file, removed patch reference from talconfig.yaml, applied configuration changes to nami node removing baseRuntimeSpecOverrides.

Repository code quality enhancement: Implemented comprehensive improvements through 8 logical commits including pre-commit hooks with YAML validation, kustomize build checks, kubectl dry-run validation, yamllint configuration optimized for Kubernetes manifests. Enhanced app-scout script with improved type hints and file discovery capabilities.

### 2025-07-09 - CUPS Print Server Deployment Troubleshooting

Successfully deployed CUPS print server to Kubernetes with comprehensive troubleshooting and configuration fixes. Fixed Docker 23.x NOFILE limit issue by implementing baseRuntimeSpecOverrides in Talos configuration setting RLIMIT_NOFILE to 65536 for nami node.

Resolved HelmRelease stalling by restarting Flux controllers and forcing proper Kustomization reconciliation. Fixed SECRET_DOMAIN variable substitution and removed problematic UDP port configuration causing NodePort conflicts.

Core issue identified: Even with proper Docker 23.x NOFILE limit fix applied at Talos level, CUPS systemd socket activation still failing. Process running but no TCP sockets listening, LoadBalancer IP unreachable.

### 2025-07-06 - Authentik Database Authentication Issues Resolved

Successfully diagnosed and fixed Authentik deployment authentication failures through systematic investigation using kubectl exec commands.

PostgreSQL Issue Resolved: Found authentik user password was not properly set during database initialization. Used postgres superuser to reset authentik user password. Redis Issue Identified: Discovered Redis authentication failures due to missing password configuration in Authentik values.

Authentik Migration Complete: Full deployment successful with working authentication. All components operational - PostgreSQL, Redis, authentik-server, authentik-worker pods Running/Ready. HTTPRoute active at auth-test.dailey.app via Cloudflare tunnel. Admin credentials tested and verified working.

### 2025-07-05 - Authentik Migration Planning and Infrastructure Development

Completed comprehensive Authentik migration planning including analysis, architecture decisions, and repository pattern standardization. Established self-contained application structure following repository conventions with co-located HelmRepository resources.

App Scout Research Tool Refactoring: Successfully completed comprehensive refactoring implementing approved two-phase discovery system. Script now provides discover command for complete landscape analysis and inspect command for targeted file fetching using exact GitHub paths.

Rook Ceph Storage Infrastructure Completion: Achieved full operational status with HEALTH_OK across all components. Successfully resolved OSD creation issues by implementing stable device identifiers. All 3 OSDs operational with ~5TB total storage available.

### 2025-07-04 - NFS Infrastructure Implementation

Completed NFS infrastructure setup with static PersistentVolumes for existing Unraid data. Created comprehensive storage structure with three main PVs: media-pv (100Ti), photos-pv (10Ti), and filerun-pv (5Ti) pointing to existing Nezuko shares.

Implemented security configurations with NFSv4.1 and Private mode for local network access. PVs configured with ReadWriteMany access mode for shared storage access patterns.

### 2025-07-02 - App Scout Research Tooling Implementation

Created comprehensive app-scout.py tool for systematic service migration analysis. Tool provides programmatic access to kubesearch.dev community data with 6,395+ app-template deployments and examples from 38+ repositories.

Implemented 4-step migration methodology: discovery → configuration analysis → Docker Compose comparison → implementation decision. Tool fetches actual HelmRelease and values.yaml files from community repositories for direct configuration comparison.

### 2025-06-30 - Rook Ceph Infrastructure Implementation

Implemented Rook Ceph storage infrastructure following repository conventions. Created complete directory structure with operator and cluster components using official Helm charts. Fixed Talos disk selector ambiguity on rias node with size filter.

Resolved multiple YAML configuration conflicts by analyzing repository patterns and removing inline values from HelmReleases. Added proper top-level monitoring configuration for Helm chart Prometheus integration.

### 2025-06-29 - Session Created

Created session to track comprehensive Docker to Kubernetes migration. Initial focus: reviewing master plan and beginning Phase 1 infrastructure foundation with Rook Ceph deployment. Objectives: Migrate 42+ services across 6 phases, maintain availability, establish GitOps practices.
