# Session: Docker to Kubernetes Migration

## Status

- **Phase**: Implementation
- **Progress**: 15/275 items complete (Phase 1 Infrastructure Foundation complete)

## Objective

Migrate 42+ Docker services from Nezuko (Unraid) to the 3-node Talos Kubernetes cluster. The migration prioritizes infrastructure readiness, dependency management, and incremental learning while maintaining service availability throughout the transition.

## Current Focus

Ready to begin Phase 2 Authentication & Core Services with Authentik deployment. Phase 1 Infrastructure Foundation completed successfully with all core systems operational: Rook Ceph storage (HEALTH_OK), NFS static PVs (115Ti), Envoy Gateway (fully migrated from Cilium), enhanced validation infrastructure, and migration tooling.

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
- [x] Complete Envoy Gateway migration cutover (HTTPRoute updates and Cilium cleanup) - PHASE 1 INFRASTRUCTURE FOUNDATION COMPLETE
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

1. Deploy Authentik PostgreSQL and Redis backend components using app-template
2. Configure Authentik HelmRelease with auth.${SECRET_DOMAIN} subdomain (production deployment)
3. Export existing user data and configuration from SWAG Authentik instance
4. Import user data and test authentication flow with existing OIDC integrations
5. Begin migrating AdGuard Home with single replica and cluster DNS configuration

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
- Internal Gateway: 192.168.1.72 (Envoy Gateway - internal services)
- External Gateway: 192.168.1.73 (Envoy Gateway - external/public services)
- Domain: dailey.app, Test Domain: *.test.dailey.app
- Cloudflare Tunnel ID: 6b689c5b-81a9-468e-9019-5892b3390500
- Tunnel Target: external.dailey.app → 192.168.1.73

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

### 2025-07-12 - Envoy Gateway Migration Completion and Phase 1 Milestone

Completed Envoy Gateway migration from Cilium to Envoy with systematic HTTPRoute cutover, infrastructure cleanup, and validation. Successfully finished Phase 1 Infrastructure Foundation with all core systems operational and ready for Phase 2 authentication services.

Migration Completion: Updated all HTTPRoute parentRefs from kube-system to network namespace (authentik, flux-instance, rook-ceph). Verified service accessibility through new gateways before infrastructure cleanup. Removed old Cilium gateway resources and CiliumGatewayClasses from kube-system namespace. Confirmed external-dns updated DNS records for new gateway infrastructure.

Root Cause Analysis: Initial incomplete cutover occurred because migration deployment created new infrastructure but didn't update existing HTTPRoute references. Systematic investigation revealed all services still routing through old Cilium gateways despite new Envoy infrastructure being operational. Resolution required coordinated namespace reference updates and infrastructure cleanup.

Phase 1 Status: Infrastructure Foundation complete with Rook Ceph (HEALTH_OK, 3 OSDs operational), NFS storage (static PVs for 115Ti Unraid data), Envoy Gateway (complete migration from Cilium), external-dns (automatic DNS management), enhanced validation (server-side kubectl with SOPS), Homer dashboard (operational), and app-scout tooling (migration analysis capabilities).

### 2025-07-12 - Envoy Gateway Migration Infrastructure Implementation

Successfully migrated from Cilium to Envoy Gateway for Gateway API implementation with comprehensive server-side validation. Replaced legacy gateway infrastructure with modern Envoy Gateway supporting SecurityPolicy for forward authentication capabilities.

Migration Components: Created complete Envoy Gateway deployment with HelmRelease using official oci://docker.io/envoyproxy/gateway-helm chart v1.4.1. Deployed GatewayClass resource with gateway.envoyproxy.io/gatewayclass-controller. Migrated internal/external Gateway resources from kube-system/cilium to network/envoy-gateway namespace. Updated gatewayClassName from 'cilium' to 'envoy' maintaining same VIPs (192.168.1.72/73).

Enhanced Validation Infrastructure: Implemented custom validation script scripts/validate-sops-k8s.sh with SOPS decryption and template variable resolution. Upgraded pre-commit hooks from client-side to server-side kubectl validation. Script handles SOPS encrypted secrets, substitutes ${SECRET_DOMAIN} template variables using real decrypted values, validates against Kubernetes API with admission controllers.

Technical Implementation: Validation script achieves 830ms performance for full repository, uses envsubst for reliable template substitution, implements repository root discovery for portable execution. Pre-commit integration provides production-grade validation catching CRD violations, admission controller issues, and security policy problems before deployment.

Decision Rationale: Envoy Gateway selected over Istio for simpler architecture without service mesh overhead while providing SecurityPolicy CRD for forward authentication. Migration maintains operational continuity with same VIPs, gateway names, and certificate infrastructure.

### 2025-07-11 - Infrastructure Phase Completion and System Enhancement

Completed Phase 1 Infrastructure Foundation with enhanced memory bank system rules and repository code quality improvements. Achieved 15/275 items complete with comprehensive validation infrastructure and template structure compliance.

Memory Bank Enhancement: Implemented template structure compliance enforcement with authorized top-level sections, Resources sub-section organization, comprehensive consolidation across all sections. Enhanced validation checklist with structure compliance verification and file size management targets.

Infrastructure Cleanup: Completed CUPS service removal from Kubernetes due to persistent systemd socket activation issues with Docker 23.x containers. Removed all CUPS application files, reverted Talos configuration changes, implemented comprehensive repository code quality enhancements.

### 2025-07-10 - CUPS Service Analysis and Repository Enhancement

Systematically analyzed CUPS deployment issues including Docker 23.x NOFILE limits, systemd socket activation failures, and container runtime limitations. Applied Talos baseRuntimeSpecOverrides with RLIMIT_NOFILE 65536 but persistent issues led to decision for external CUPS deployment.

Repository Enhancement: Implemented comprehensive code quality improvements with pre-commit hooks for YAML validation, kustomize build checks, kubectl dry-run validation, and yamllint configuration. Enhanced app-scout script with improved type hints and file discovery capabilities.

### 2025-07-09 - CUPS Deployment and Flux Troubleshooting

Deployed CUPS print server with comprehensive troubleshooting including Docker 23.x NOFILE limits, HelmRelease stalling, and SECRET_DOMAIN substitution. Fixed multiple configuration issues but identified core systemd socket activation limitation requiring external deployment approach.

### 2025-07-06 - Authentik Migration Complete

Successfully completed Authentik deployment with systematic authentication troubleshooting. Resolved PostgreSQL user password initialization and Redis authentication configuration. All components operational with HTTPRoute active at auth-test.dailey.app and admin credentials verified working.

### 2025-07-05 - Authentik Planning and Infrastructure Development

Completed comprehensive Authentik migration planning including analysis, architecture decisions, and repository pattern standardization. Established self-contained application structure following repository conventions with co-located HelmRepository resources.

App Scout Research Tool Refactoring: Successfully completed comprehensive refactoring implementing approved two-phase discovery system. Script now provides discover command for complete landscape analysis and inspect command for targeted file fetching using exact GitHub paths.

Rook Ceph Storage Infrastructure Completion: Achieved full operational status with HEALTH_OK across all components. Successfully resolved OSD creation issues by implementing stable device identifiers. All 3 OSDs operational with ~5TB total storage available.

### 2025-07-04 to 2025-07-02 - Infrastructure Foundation Development

Completed comprehensive infrastructure foundation including NFS storage setup, App Scout research tooling, and Rook Ceph deployment. Established static PersistentVolumes for Unraid data (media 100Ti, photos 10Ti, filerun 5Ti) with NFSv4.1 security. Created app-scout.py tool for systematic service migration analysis with 6,395+ community examples.

### 2025-06-30 - Rook Ceph Storage Implementation

Implemented comprehensive Rook Ceph storage infrastructure with operator and cluster components using official Helm charts. Resolved Talos disk selector ambiguity and YAML configuration conflicts. Fixed multiple repository pattern violations and achieved HEALTH_OK status with 3 OSDs operational (~5TB total storage).

### 2025-06-29 - Session Created

Created session to track comprehensive Docker to Kubernetes migration with 42+ services across 6 phases. Initial focus on Phase 1 infrastructure foundation including Rook Ceph deployment, NFS storage, and migration tooling development. Objectives: maintain service availability, establish GitOps practices, implement systematic migration methodology.
