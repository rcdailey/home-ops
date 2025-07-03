# Session: Docker to Kubernetes Migration

## Status

- **Phase**: Implementation
- **Progress**: 3/275 items complete

## Objective

Migrate 42+ Docker services from Nezuko (Unraid) to the 3-node Talos Kubernetes cluster. The migration prioritizes infrastructure readiness, dependency management, and incremental learning while maintaining service availability throughout the transition.

## Current Focus

Helm chart research and selection tooling completed. Ready to begin individual service migrations using systematic analysis approach with helm-search.py tool for configuration discovery and comparison.

## Task Checklist

### Phase 1: Infrastructure Foundation
- [x] Deploy Rook Ceph cluster across all 3 nodes
- [x] Configure Ceph storage classes (SSD performance tier)
- [x] Create Helm chart research and analysis tooling (helm-search.py)
- [ ] Set up NFS CSI driver for Unraid share access
- [ ] Create persistent volume claims for major applications
- [ ] Test storage performance and failover scenarios
- [ ] Deploy external-dns for automatic DNS record management
- [ ] Configure additional network policies for service isolation
- [ ] Set up VPN integration solution for qBittorrent
- [ ] Validate internal and external gateway routing
- [ ] Deploy Kubernetes-native backup solution (Velero or similar)
- [ ] Set up cluster monitoring (Prometheus/Grafana stack)
- [ ] Configure log aggregation for troubleshooting
- [ ] Implement service mesh if needed for complex networking

### Phase 2: Authentication & Core Services
- [ ] Deploy Authentik server and worker components
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
- [ ] Deploy Homer homepage dashboard
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

1. Set up NFS CSI driver for Unraid share access
2. Test storage performance and failover scenarios for Rook Ceph
3. Create persistent volume claims for major applications
4. Deploy external-dns for automatic DNS record management
5. Establish weekly progress reviews and checkpoint meetings

## Service Migration Methodology

### **Systematic Analysis Workflow**

For each service migration, we follow this proven 4-step process using the helm-search.py tool and Claude for analysis:

#### **Step 1: Chart Discovery**
```bash
# Find available charts and app-template examples
scripts/helm-search.py search <service-name>

# Example output shows:
# - Repository names with star counts
# - Chart types (official vs app-template)
# - URLs to actual configurations
# - Release names and versions
```

#### **Step 2: Configuration Analysis**
```bash
# Fetch specific repository's configuration
scripts/helm-search.py fetch <service-name> --repo <repo-name> --type both

# Downloads and displays:
# - HelmRelease YAML (Flux integration)
# - values.yaml files (detailed configuration)
# - Companion configuration files
```

#### **Step 3: Docker Compose Comparison**
Claude analyzes:
- Current Docker Compose setup vs Helm chart capabilities
- Storage requirements (NFS mounts, Rook Ceph PVCs)
- Network configuration (ports, ingress, DNS)
- Environment variables and secrets management
- Resource requirements and security contexts
- Hardware requirements (GPU access, special capabilities)

#### **Step 4: Migration Decision & Implementation**
Based on analysis, Claude recommends:
- Best chart option (app-template vs official chart)
- Required repository additions to Flux
- HelmRelease configuration following repository patterns
- Storage class selections and PVC requirements
- Secret management and configuration approach

### **Chart Selection Strategy**

**Primary Choice: bjw-s app-template**
- 6,395+ community deployments
- Consistent patterns across all services
- Maximum flexibility for custom configurations
- Best integration with repository conventions

**Secondary Choice: Official Helm Charts**
- Complex applications (Authentik, databases)
- Charts with significant operational value
- Active maintenance and community support

**Decision Factors:**
1. **Complexity**: Simple apps → app-template, complex → official charts
2. **Community**: Higher star repositories = proven configurations
3. **Flexibility**: Custom needs → app-template, standard needs → official charts
4. **Maintenance**: Repository activity and chart update frequency

### **Tool Reference**

**scripts/helm-search.py Commands:**
```bash
# Discovery commands (JSON output)
scripts/helm-search.py search <chart-name> [--limit N]
scripts/helm-search.py stats <chart-name>
scripts/helm-search.py app-template [--limit N]
scripts/helm-search.py migration-batch

# Configuration fetching (human-readable output)
scripts/helm-search.py fetch <chart-name> --repo <repo-name> [--type helm|values|both]
```

**Database Location:** `scripts/repos.db` and `scripts/repos-extended.db`
**Data Source:** kubesearch.dev community repository index

## Resources

### Configuration Files
- Master Plan: `MIGRATION_MASTER_PLAN.md`
- Talos Config: `talos/talconfig.yaml`
- Task Definitions: `Taskfile.yaml`
- Secret Management: `.sops.yaml`, `age.key`
- Kubeconfig: `kubeconfig`

### Network Configuration
- Network: 192.168.1.0/24
- Gateway: 192.168.1.1
- Cluster API: 192.168.1.70
- DNS Gateway: 192.168.1.71 (k8s_gateway)
- Internal Gateway: 192.168.1.72 (for internal services)
- External Gateway: 192.168.1.73 (for external/public services)

### Node Details
- rias: 192.168.1.61 - VM on lucy/Proxmox, /dev/sda, MAC: bc:24:11:a7:98:2d
- nami: 192.168.1.50 - Intel NUC, /dev/sda, MAC: 94:c6:91:a1:e5:e8
- marin: 192.168.1.59 - Intel NUC, /dev/nvme0n1, MAC: 1c:69:7a:0d:8d:99

### Domain and External Access
- Domain: dailey.app
- Test Domain: *.test.dailey.app
- Cloudflare Tunnel ID: 6b689c5b-81a9-468e-9019-5892b3390500
- Tunnel Target: external.dailey.app → 192.168.1.73

### Storage Strategy
- Rook Ceph: All available node storage for application data and config
- NFS Mounts from Unraid:
  - /mnt/user/media - Movies, TV shows, music
  - /mnt/user/photos - Photo storage for Immich
  - /mnt/user/filerun - FileRun cloud storage

### Service Categories and Counts
1. Databases & Data Stores (12 services) - PostgreSQL, MariaDB, MongoDB, Redis, Elasticsearch
2. Media Management Suite (13 services) - Plex, *arr stack, downloaders, enhancement tools
3. Web Applications (5 services) - LibreChat, FileRun, Immich, BookStack, Uptime Kuma
4. Infrastructure & Networking (4 services) - SWAG, AdGuard, Cloudflared, Docker proxy
5. Identity & Authentication (2 services) - Authentik server and worker
6. AI/ML Services (3 services) - Immich ML, LibreChat RAG, LiteLLM
7. Utilities & Tools (5 services) - Borgmatic, Deck Chores, maintenance utilities
8. Dashboards & Monitoring (1 service) - Homer dashboard

### Services to Skip Migration
- LibreChat stack (4 services) - No longer actively used
- Stash - Skip for now, evaluate later
- Borgmatic - Replace with Kubernetes-native backup solution
- Deck Chores - Replace with Kubernetes CronJobs
- Plex Bloat Fix - Evaluate need in K8s environment

### High-Complexity Migration Considerations
- qBittorrent: Requires VPN connectivity for all traffic
- AdGuard Home: Needs UDP port 53 for DNS (host networking)
- Authentik: Critical dependency for many services
- Plex: Intel GPU access for hardware transcoding
- Media Stack: 13 services with complex networking and shared storage
- Immich Components: Deploy as service group with shared storage strategy

### Timeline Estimates
- Phase 1 (Infrastructure): 1-2 weeks
- Phase 2 (Authentication/Core): 1-2 weeks
- Phase 3 (Media Infrastructure): 2-3 weeks
- Phase 4 (Productivity Apps): 2-3 weeks
- Phase 5 (Utilities): 1 week
- Phase 6 (Optimization): 1 week
- Total Estimated Duration: 8-12 weeks with learning and testing time

## Progress & Context Log

### 2025-07-02 - Helm Chart Research Tooling Implementation

Created comprehensive helm-search.py tool for systematic service migration analysis. Tool provides programmatic access to kubesearch.dev community data with 6,395+ app-template deployments and examples from 38+ repositories.

Implemented 4-step migration methodology: discovery → configuration analysis → Docker Compose comparison → implementation decision. Tool fetches actual HelmRelease and values.yaml files from community repositories for direct configuration comparison.

Key capabilities: search charts by popularity, fetch configurations from specific repositories, analyze app-template vs official chart usage patterns, export JSON data for programmatic analysis. Database files (repos.db, repos-extended.db) stored in scripts directory with relative path resolution.

Established systematic approach for all future service migrations using community-proven configurations as starting points. Ready to begin individual service analysis and migration planning.

### 2025-06-30 - Rook Ceph Infrastructure Implementation

Implemented Rook Ceph storage infrastructure following repository conventions. Created complete directory structure with operator and cluster components using official Helm charts. Fixed Talos disk selector ambiguity on rias node with size filter. 

Resolved multiple YAML configuration conflicts by analyzing repository patterns and removing inline values from HelmReleases. Added proper top-level monitoring configuration for Helm chart Prometheus integration alongside cephClusterSpec monitoring.

Rook Ceph cluster deployment completed successfully. All storage components operational with proper monitoring integration. Storage classes configured for SSD performance tier. Infrastructure foundation ready for next phase components.

### 2025-06-29 - Session Created

Created session to track comprehensive Docker to Kubernetes migration. Initial focus: reviewing master plan and beginning Phase 1 infrastructure foundation with Rook Ceph deployment.
Objectives: Migrate 42+ services across 6 phases, maintain availability, establish GitOps practices.