# Session: Docker to Kubernetes Migration

## Status

- **Phase**: Implementation
- **Progress**: 19/275 items complete (Phase 1 Infrastructure Foundation complete, qBittorrent operational, DNS architecture complete with AdGuard Home production deployment)

## Objective

Migrate 42+ Docker services from Nezuko (Unraid) to the 5-node Talos Kubernetes cluster (3 control-plane + 2 workers). The migration prioritizes infrastructure readiness, dependency management, and incremental learning while maintaining service availability throughout the transition.

## Current Focus

DNS architecture completed with AdGuard Home production deployment featuring VLAN-based filtering, client IP preservation, and conditional forwarding. qBittorrent deployment complete with optimized configuration applied via WebUI. Production-ready setup includes VueTorrent UI, 20MB/s speed limits, 4:1 share ratios, 12-hour seeding limits, proper download paths, and subnet authentication whitelist. Forward authentication operational with Authentik, VPN connectivity stable with ProtonVPN port forwarding.

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
- [x] Deploy AdGuard Home with high availability (primary-replica setup)
- [x] Configure VLAN-based filtering with client IP preservation
- [x] Implement conditional forwarding for local domain resolution
- [x] Complete DNS architecture with external-dns automation
- [ ] Deploy FileRun with MariaDB StatefulSet
- [ ] Deploy Elasticsearch for search functionality
- [ ] Deploy Tika for document processing
- [ ] Mount existing /mnt/user/filerun NFS share
- [ ] Test file upload/download and search functionality

### Phase 3: Media Infrastructure

- [x] Deploy qBittorrent with Gluetun VPN sidecar (simplified 3-container pod: gluetun, qbittorrent, port-forward)
- [x] Configure ProtonVPN WireGuard with direct DNS (no dnsdist complexity)
- [x] Mount NFS downloads (unraid-media-pv) and Ceph config storage
- [x] Configure VPN credentials and validate Wireguard connectivity
- [x] Configure SecurityPolicy for Envoy Gateway forward authentication
- [x] Apply optimized configuration via WebUI (VueTorrent, speed limits, share ratios, paths)
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

1. Begin next media infrastructure service (SABnzbd or Prowlarr)
2. Apply forward authentication pattern to additional applications
3. Continue Phase 3 media infrastructure deployment
4. Consider production cutover to torrent.${SECRET_DOMAIN} after stability validation

## Resources

### Implementation Plans

#### Service Migration Methodology

**Systematic Analysis Workflow**: For each service migration, we follow this proven 4-step process using the app-scout tool and Claude for analysis:

1. **Chart Discovery**: `scripts/app-scout.sh discover <service-name>` - Find available charts and app-template examples
2. **Configuration Analysis**: `scripts/app-scout.sh inspect <service-name> --repo <repo-name> --files helmrelease,values` - Fetch specific repository's configuration
3. **Docker Compose Comparison**: Claude analyzes current Docker Compose setup vs Helm chart capabilities, storage requirements, network configuration, environment variables and secrets management
4. **Migration Decision & Implementation**: Based on analysis, Claude recommends best chart option, required repository additions to Flux, HelmRelease configuration following repository patterns

**Chart Selection Strategy**: Primary choice is bjw-s app-template (6,395+ community deployments) for consistent patterns and maximum flexibility. Secondary choice is official Helm charts for complex applications with significant operational value.

#### qBittorrent Migration Plan

**Migration Strategy**: ProtonVPN WireGuard implementation with 4-container pod deployment, forward authentication via SecurityPolicy, and dual storage configuration following repository conventions.

**VPN Architecture**: Gluetun ProtonVPN integration (v3.39.1) with simplified container architecture - gluetun VPN init container, qbittorrent main container, port-forward sync sidecar. Direct ProtonVPN DNS eliminates dnsdist complexity. Manual WireGuard private key configuration, NAT-PMP port forwarding, validated cryptographic keys. NET_ADMIN capabilities, /dev/net/tun device.

**Directory Structure**: kubernetes/apps/default/qbittorrent/ following repository conventions - app/ directory (helmrelease.yaml, httproute.yaml, securitypolicy.yaml), secrets/ directory (secret.sops.yaml with SOPS encryption), ks.yaml at root level. Default namespace pattern with established repository structure.

**Forward Authentication**: Envoy Gateway SecurityPolicy with external authentication (extAuth) targeting qBittorrent HTTPRoute specifically. Backend points to authentik-server:80 at /outpost.goauthentik.io/auth endpoint. Headers forwarded: x-authentik-user, x-authentik-groups. Opt-in per-HTTPRoute pattern enabling selective authentication without gateway-wide enforcement.

**Storage Configuration**: NFS unraid-media-pv (100Ti) for downloads at /media/.torrents subpath, Rook Ceph ceph-block StorageClass for configuration persistence. Mirrors Docker mapping with enhanced replication and persistence.

**Deployment Components**: bjw-s app-template chart, default namespace, ProtonVPN WireGuard provider with manual key configuration, automatic port forwarding via NAT-PMP, simplified DNS architecture (no dnsdist), torrent-test.${SECRET_DOMAIN} initial subdomain.

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

**qBittorrent Research**: 118 app-template deployments vs 2 dedicated charts. Key repositories analyzed: ahinko/home-ops (active VPN), bjw-s-labs/home-ops (commented VPN), onedr0p/home-ops (no VPN). VPN pattern consensus: Gluetun sidecar with port-forward sync container, NET_ADMIN capabilities. Production deployment simplified DNS architecture by removing dnsdist proxy complexity.

**VPN Provider Analysis**: Comprehensive automation comparison revealing TorGuard limitations (manual config generation, no API automation, custom gluetun setup) versus Mullvad/ProtonVPN full automation (API-based config, dynamic port forwarding, native gluetun support). Research sources: Perplexity analysis of 2024-2025 developments, TorGuard documentation updates, community deployment patterns.

**Forward Auth Research**: Envoy Gateway SecurityPolicy external authentication (extAuth) analysis with HTTP backend configuration. Per-HTTPRoute targeting enables opt-in authentication model. SecurityPolicy targets specific HTTPRoute rather than Gateway-wide enforcement, providing granular control over which applications require authentication.

**Repository Structure Analysis**: Complete directory pattern analysis revealing kubernetes/apps/default/ namespace convention, app/ and secrets/ subdirectory patterns, SOPS encryption standards, HTTPRoute co-location with HelmRelease. Authentik deployment example confirms established patterns for new application deployments.

### Configuration Files

- Master Plan: `MIGRATION_MASTER_PLAN.md`
- Talos Config: `talos/talconfig.yaml`
- Task Definitions: `Taskfile.yaml`
- Secret Management: `.sops.yaml`, `age.key`
- Kubeconfig: `kubeconfig`

### Network Configuration

- Network: 192.168.1.0/24, Gateway: 192.168.1.1, Cluster API: 192.168.1.70
- DNS Gateway: 192.168.1.71 (AdGuard Home with VLAN-based filtering)
- Internal Gateway: 192.168.1.72 (Envoy Gateway - internal services)
- External Gateway: 192.168.1.73 (Envoy Gateway - external/public services)
- Domain: ${SECRET_DOMAIN}, Test Domain: *.test.${SECRET_DOMAIN}
- Cloudflare Tunnel ID: 6b689c5b-81a9-468e-9019-5892b3390500
- Tunnel Target: external.${SECRET_DOMAIN} → 192.168.1.73

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

### 2025-08-16 - DNS Architecture Production Deployment Complete

Successfully completed DNS architecture migration with AdGuard Home production deployment, achieving all design goals for local traffic optimization, VLAN-based filtering, and service migration support.

**Production Cutover**: Renamed `dns-test` subdomain to `dns` marking official production promotion. Created separate `dns-replica` subdomain for direct replica instance access, enabling independent configuration verification and management.

**Client IP Preservation Solution**: Implemented direct client connection architecture where devices connect directly to AdGuard Home (192.168.1.71) instead of through UDMP DNS forwarding. This preserves real source IPs enabling VLAN-based filtering with 590,523+ rules across 5 network segments: Main LAN (global rules), Kids VLAN (parental controls), IoT/Work VLANs (social media blocking), Guest VLAN (basic protection), Cameras VLAN (minimal filtering).

**Local Traffic Optimization**: Configured conditional forwarding ensuring `*.domain.com` queries resolve locally through UDMP records, enabling direct connections to cluster gateways without inefficient WAN routing through Cloudflare infrastructure.

**Service Migration Architecture**: Established wildcard fallback records (`*.domain.com` → Unraid) with automatic specific record overrides as services migrate to Kubernetes. External-DNS dual-provider setup automatically manages both UDMP (local) and Cloudflare (public) DNS records based on HTTPRoute configurations.

**Operational Benefits**: DNS architecture now supports seamless Docker-to-Kubernetes migration with zero-downtime DNS updates, maintains family-friendly filtering across different VLANs, and provides efficient local traffic routing while preserving external internet access through Cloudflare tunnel integration.

### 2025-07-14 - qBittorrent Configuration Complete

Completed qBittorrent deployment with optimized configuration applied through WebUI manual settings. Service now production-ready with all performance and functionality enhancements configured.

Configuration Applied: Updated WebUI settings to match optimized Docker configuration including username change to 'voidpointer', VueTorrent alternative UI enabled (/app/vuetorrent), speed limits set to 20MB/s up/down, share ratio limiting at 4:1, seeding time limit 12 hours. Download paths configured: /media/.torrents/complete and /media/.torrents/incomplete. Authentication subnet whitelist 192.168.1.0/24 enabled, queuing system disabled for optimal performance.

Config Migration Approach: Direct WebUI configuration chosen over file copying due to qBittorrent overwriting config files on graceful shutdown. Manual configuration ensures persistence through container restarts while maintaining all optimizations from previous Docker deployment. Authentication credentials now use container-specific password rather than inherited hash.

Operational Status: qBittorrent fully functional with forward authentication via Authentik, VPN connectivity through ProtonVPN WireGuard, automatic port forwarding (current port 51967), and optimized performance settings. Ready for production workloads with all Docker Compose feature parity achieved.

Deployment Pattern: Established complete qBittorrent deployment template including VPN integration, forward authentication, performance optimization, and manual configuration workflow. Pattern ready for replication across additional torrent services if needed.

### 2025-07-14 - qBittorrent Forward Authentication Success

Successfully implemented Authentik forward authentication for qBittorrent using Envoy Gateway SecurityPolicy with embedded outpost integration. Resolved complex authentication issues through systematic debugging and proper header configuration.

Root Cause Analysis: Initial authentication failures caused by missing headersToExtAuth configuration in SecurityPolicy, preventing proper cookie and forward auth header handling between Envoy Gateway and Authentik embedded outpost. Testing revealed endpoint existed at /outpost.goauthentik.io/auth/envoy but was returning 302 redirects instead of proper 401/200 responses due to missing session context.

Configuration Solution: Added critical headersToExtAuth field to SecurityPolicy with cookie, x-forwarded-host, and x-forwarded-proto headers. Updated headersToBackend to include set-cookie and corrected header names to match Authentik specifications. Configured Authentik proxy provider in "Forward auth (domain level)" mode with proper external/internal host settings.

Authentik Integration: Created dedicated proxy provider for qBittorrent with domain-level forward auth mode, external host https://torrent-test.${SECRET_DOMAIN}, internal host http://qbittorrent.default.svc.cluster.local:8080. Configured embedded outpost with authentik_host set to https://auth-test.${SECRET_DOMAIN} and assigned qBittorrent application.

Technical Implementation: SecurityPolicy targeting ak-outpost-authentik-embedded-outpost:9000 service with correct /outpost.goauthentik.io/auth/envoy endpoint. Headers configuration enables session cookie forwarding and proper host detection for Authentik provider matching. Authentication flow: unauthenticated requests → 302 OAuth redirect → Authentik login → authenticated access to qBittorrent.

Validation Results: Forward authentication operational with proper OAuth flow redirecting unauthenticated users to auth-test.${SECRET_DOMAIN} login. Post-authentication access to torrent-test.${SECRET_DOMAIN} succeeds with user context headers forwarded to qBittorrent. VPN connectivity maintained through ProtonVPN WireGuard with port forwarding active.

Pattern Established: Envoy Gateway SecurityPolicy + Authentik embedded outpost integration provides reusable authentication pattern for additional applications. Configuration template ready for SABnzbd, Prowlarr, and other media infrastructure services requiring forward authentication.

### 2025-07-13 - qBittorrent DNS Health Check Resolution

Successfully resolved gluetun health check failures by eliminating dnsdist DNS proxy complexity and configuring direct ProtonVPN DNS usage. Pod now stable with successful health checks, operational VPN connectivity, and zero DNS leaks.

Root Cause Analysis: Investigated recurring health check failures showing continuous VPN restarts every 15-20 seconds. Discovered dnsdist DNS proxy failed to resolve kube-dns.kube-system.svc.cluster.local service name, creating circular DNS dependency. Gluetun health check to cloudflare.com:443 consistently timed out due to broken DNS resolution chain.

DNS Architecture Simplification: Removed dnsdist initContainer entirely, eliminating unnecessary DNS proxy layer. Updated gluetun configuration to DNS_ADDRESS="" (empty) enabling direct ProtonVPN DNS server usage. Simplified container architecture from 4-container pod (dnsdist, gluetun, qbittorrent, port-forward) to 3-container pod (gluetun, qbittorrent, port-forward).

Configuration Changes: Deleted dnsdist-configmap.yaml and associated volume mounts, removed dnsdist initContainer from helmrelease.yaml, updated kustomization.yaml resources. Maintained security through VPN tunnel DNS routing while eliminating complexity that provided no additional benefit.

Validation Results: Pod operational for 30+ minutes with stable VPN connection to Singapore endpoint (149.34.253.247), successful health check ("INFO [healthcheck] healthy!"), active port forwarding (port 42469), regular API calls from port-sync container. No restart loops or DNS timeout errors.

Technical Learning: Demonstrated that DNS proxy layers can introduce failure points without security benefits. ProtonVPN DNS servers provide secure resolution through VPN tunnel while maintaining simplicity. Over-engineering DNS architecture created brittleness that simple direct configuration avoided.

Security Validation: Confirmed zero DNS leaks with direct ProtonVPN DNS usage through VPN tunnel. All DNS traffic routed through VPN provider infrastructure (1.1.1.1 via ProtonVPN) rather than local cluster DNS. Simplified architecture maintains security objective while improving reliability.

### 2025-07-12 - VPN Provider Analysis and TorGuard Automation Research

Conducted comprehensive research into VPN provider automation capabilities for qBittorrent deployment, comparing TorGuard (current provider) against automation-friendly alternatives like Mullvad and ProtonVPN.

TorGuard Automation Limitations: Research revealed significant gaps in TorGuard's containerized automation support. No API exists for automated WireGuard config generation, requiring manual configuration through web interface. Port forwarding requires manual requests and lacks dynamic update capabilities. Gluetun integration works but requires custom provider configuration rather than native support.

VPN Provider Comparison Matrix: Mullvad provides full automation with API-based config generation, automatic port forwarding, native gluetun support, and dynamic port updates. ProtonVPN offers similar automation capabilities. TorGuard requires manual intervention for all configuration management and port assignments, representing a legacy approach for containerized deployments.

Port Forwarding Education: Clarified VPN port forwarding necessity for qBittorrent performance. VPN providers dynamically assign ports for incoming peer connections, requiring synchronization between VPN-assigned port and qBittorrent configuration. Port-sync containers monitor VPN provider APIs and automatically update qBittorrent settings when ports change.

Architecture Visualization: Developed clear mental model of 4-container pod sharing network namespace. VPN container establishes tunnel, all other containers automatically route traffic through VPN. DNS container resolves K8s services, port-sync container maintains VPN-qBittorrent port alignment. Simplified understanding from complex multi-container coordination to shared network concept.

Decision Framework: Identified two implementation paths - Option 1: Continue with TorGuard using manual workflow (no automation benefits, known provider), Option 2: Switch to Mullvad for full automation (€5/month, complete gluetun integration, dynamic port management). Research strongly favors automation-friendly providers for production Kubernetes environments.

Current TorGuard Workflow: Uses manual WireGuard certificate generation, manual port forwarding requests through TorGuard dashboard. Would maintain this workflow in Kubernetes with custom gluetun configuration, losing automation benefits but keeping existing provider relationship.

### 2025-07-12 - Repository Structure Analysis and Forward Auth Architecture Planning

Conducted comprehensive analysis of repository structure conventions and designed forward authentication architecture for qBittorrent deployment. Refined implementation plan based on actual directory patterns and Envoy Gateway SecurityPolicy capabilities.

Repository Structure Discovery: Analyzed kubernetes/apps directory structure revealing standard pattern - applications deployed in default namespace (not media), secrets in separate directories with SOPS encryption, HTTPRoute files co-located with helmrelease. Authentik example shows app/helmrelease.yaml + app/httproute.yaml + secrets/secret.sops.yaml pattern. No existing SecurityPolicy usage found, indicating clean slate for forward auth implementation.

Forward Auth Architecture Design: Researched Envoy Gateway SecurityPolicy external authentication (extAuth) capabilities. Identified optimal opt-in pattern - SecurityPolicy targets specific HTTPRoute for granular control. External auth backend points to authentik-server:80 at /outpost.goauthentik.io/auth endpoint. Headers forwarded: x-authentik-user, x-authentik-groups. Enables per-application authentication control without gateway-wide enforcement.

VPN Architecture Clarification: Developed simplified visualization of 4-container pod concept. Single pod network namespace shared by dnsdist (DNS proxy), gluetun (VPN tunnel), qbittorrent (application), port-forward (sync). VPN container establishes tunnel first, all subsequent containers automatically route through VPN. Eliminates complex networking - containers share localhost communication.

Authentik Integration Strategy: Current setup uses auth-test.${SECRET_DOMAIN} subdomain for testing, production auth.${SECRET_DOMAIN} planned. Outpost configuration required for /outpost.goauthentik.io/auth forward auth endpoint. Application and provider setup needed in Authentik for domain-level protection. Policy configuration determines access control for qBittorrent.

Directory Structure Refinement: Corrected to follow repository conventions - kubernetes/apps/default/qbittorrent/ structure with app/ (helmrelease, httproute, securitypolicy), secrets/ (secret.sops.yaml), and ks.yaml at root. Eliminates proposed media namespace and separate security directory. SOPS encryption for Mullvad VPN credentials following established pattern.

Subdomain Correction: Updated from torrent.${SECRET_DOMAIN} to torrent-test.${SECRET_DOMAIN} for initial deployment testing, matching auth-test pattern. Production cutover to torrent.${SECRET_DOMAIN} after validation. External gateway usage confirmed (192.168.1.73) for public-facing services requiring forward authentication.

### 2025-07-12 - Cloudflare Tunnel Fix and External Access Restoration

Successfully resolved external access failure for home.${SECRET_DOMAIN} by diagnosing and fixing Cloudflare tunnel configuration after Envoy Gateway migration. Root cause was outdated service reference preventing tunnel from reaching new gateway infrastructure.

Tunnel Issue Diagnosis: External DNS correctly resolved home.${SECRET_DOMAIN} to Cloudflare IPs but resulted in "Bad gateway" 502 errors. Investigation revealed tunnel config still referenced obsolete cilium-gateway-external.kube-system.svc.cluster.local service which no longer existed after Envoy migration. Tunnel logs showed DNS lookup failures preventing connection to backend services.

Stable Service Implementation: Created external-gateway.network.svc.cluster.local as stable service abstraction pointing to Envoy Gateway pods using selector-based targeting. Avoided fragile random hash service names and hardcoded IP addresses for maintainable configuration. Service provides consistent DNS endpoint regardless of underlying Envoy infrastructure changes.

Configuration Updates: Updated cloudflare-tunnel config.yaml to reference new stable service name. Cleaned up obsolete cilium-gateway Kustomization from kube-system preventing reconciliation errors. Verified tunnel established 4 successful connections to Cloudflare edge locations with no DNS lookup errors.

Technical Learning: Demonstrated importance of stable service abstractions in infrastructure migrations. Random hash service names (envoy-network-external-b1d9befd) create maintenance burden requiring updates across dependent systems. Proper Kubernetes pattern uses predictable service names as network abstraction layer.

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

Successfully completed Authentik deployment with systematic authentication troubleshooting. Resolved PostgreSQL user password initialization and Redis authentication configuration. All components operational with HTTPRoute active at auth-test.${SECRET_DOMAIN} and admin credentials verified working.

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
