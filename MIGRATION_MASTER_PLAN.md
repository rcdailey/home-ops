# Docker to Kubernetes Migration Master Plan

## Overview

This document outlines the comprehensive migration strategy for transitioning 42+ Docker services from Nezuko (Unraid) to the Talos Kubernetes cluster. The migration prioritizes infrastructure readiness, dependency management, and incremental learning while maintaining service availability.

For template repo (cluster-template) details read @README.md

## Infrastructure Context

### Current State
- **Source**: Nezuko Unraid server running Docker Compose stacks
- **Target**: 3-node Talos Kubernetes cluster (rias, nami, marin)
- **Network**: 192.168.1.0/24 with cluster VIP at 192.168.1.70
- **DNS**: Cloudflare with tunnel to 192.168.1.73 (external gateway)
- **Existing K8s**: Flux GitOps, Cilium CNI, cert-manager, external-dns

### Node Hardware Capabilities
- **rias**: 192.168.1.61 - VM on Proxmox, Intel CPU with integrated GPU
- **nami**: 192.168.1.50 - Intel NUC, Intel CPU with integrated GPU
- **marin**: 192.168.1.59 - Intel NUC, Intel CPU with integrated GPU, NVMe storage

### Storage Strategy
- **Rook Ceph**: All available node storage for application data and config
- **NFS Mounts**: Unraid shares for large media and existing data
  - `/mnt/user/media` - Movies, TV shows, music
  - `/mnt/user/photos` - Photo storage for Immich
  - `/mnt/user/filerun` - FileRun cloud storage

### Testing Strategy
- **Test Subdomain**: `*.test.<domain>` for validation before production cutover
- **DNS Precedence**: Specific DNS records override wildcard `*.<domain>`
- **Parallel Operation**: Keep SWAG running on Nezuko during migration
- **Service Cutover**: Rename test subdomain to production when ready

## Service Inventory Summary

Based on analysis of 17 Docker Compose stacks, identified **42+ individual services** across 8 functional categories:

### Core Categories
1. **Databases & Data Stores** (12 services) - PostgreSQL, MariaDB, MongoDB, Redis, Elasticsearch
2. **Media Management Suite** (13 services) - Plex, *arr stack, downloaders, enhancement tools
3. **Web Applications** (5 services) - LibreChat, FileRun, Immich, BookStack, Uptime Kuma
4. **Infrastructure & Networking** (4 services) - SWAG, AdGuard, Cloudflared, Docker proxy
5. **Identity & Authentication** (2 services) - Authentik server and worker
6. **AI/ML Services** (3 services) - Immich ML, LibreChat RAG, LiteLLM
7. **Utilities & Tools** (5 services) - Borgmatic, Deck Chores, maintenance utilities
8. **Dashboards & Monitoring** (1 service) - Homer dashboard

### Services to Skip Migration
- **LibreChat stack** (4 services) - No longer actively used
- **Stash** - Skip for now, evaluate later
- **Borgmatic** - Replace with Kubernetes-native backup solution
- **Deck Chores** - Replace with Kubernetes CronJobs
- **Plex Bloat Fix** - Evaluate need in K8s environment

## Migration Phases

### Phase 1: Infrastructure Foundation
**Goal**: Establish storage, networking, and core dependencies

#### 1.1 Storage Infrastructure
- [ ] Deploy Rook Ceph cluster across all 3 nodes
- [ ] Configure Ceph storage classes (SSD performance tier)
- [ ] Set up NFS CSI driver for Unraid share access
- [ ] Create persistent volume claims for major applications
- [ ] Test storage performance and failover scenarios

#### 1.2 Enhanced Networking
- [ ] Deploy external-dns for automatic DNS record management
- [ ] Configure additional network policies for service isolation
- [ ] Set up VPN integration solution for qBittorrent
- [ ] Validate internal and external gateway routing

#### 1.3 Monitoring & Observability
- [ ] Deploy Kubernetes-native backup solution (Velero or similar)
- [ ] Set up cluster monitoring (Prometheus/Grafana stack)
- [ ] Configure log aggregation for troubleshooting
- [ ] Implement service mesh if needed for complex networking

### Phase 2: Authentication & Core Services
**Goal**: Establish identity foundation and critical infrastructure

#### 2.1 Identity Provider (High Priority)
- [ ] **Authentik** - Deploy server and worker components
  - Export existing user data and configuration
  - Deploy as multi-container pod or separate services
  - Configure OIDC integration for other services
  - Test authentication flow before dependent services

#### 2.2 DNS & Networking
- [ ] **AdGuard Home** - DNS filtering and ad blocking
  - Start with single replica, add redundancy later
  - Configure for cluster DNS and external clients
  - Test DNS resolution and filtering rules

#### 2.3 File Management
- [ ] **FileRun** - Cloud file management with database
  - Deploy MariaDB StatefulSet
  - Deploy Elasticsearch for search functionality
  - Deploy Tika for document processing
  - Mount existing `/mnt/user/filerun` NFS share
  - Test file upload/download and search functionality

### Phase 3: Media Infrastructure
**Goal**: Establish media streaming and management foundation

#### 3.1 Core Media Server
- [ ] **Plex** - Central media streaming platform
  - Configure Intel GPU access for hardware transcoding
  - Mount `/mnt/user/media` NFS share for existing content
  - Use Rook Ceph for metadata and configuration
  - Test transcoding and client access
  - **Note**: Should be last in media stack due to dependencies

#### 3.2 Download Infrastructure
- [ ] **qBittorrent** - BitTorrent client with VPN
  - Deploy with VPN sidecar or integrate with cluster VPN
  - Configure network policies for security
  - Mount download directories via NFS
  - Test VPN connectivity and download functionality

- [ ] **SABnzbd** - Usenet downloader
  - Configure for usenet provider integration
  - Mount download directories via NFS
  - Test download and processing pipeline

#### 3.3 Content Management (*arr Stack)
**Deploy as coordinated group due to tight integration**

- [ ] **Prowlarr** - Indexer management hub (deploy first)
- [ ] **Sonarr** - TV show automation
- [ ] **Sonarr Anime** - Anime TV management
- [ ] **Radarr** - Movie automation
- [ ] **Radarr 4K** - 4K movie management
- [ ] **Radarr Anime** - Anime movie management
- [ ] **Bazarr** - Subtitle management

#### 3.4 Enhancement Services
- [ ] **Overseerr** - Request management interface
- [ ] **Tautulli** - Plex analytics and monitoring
- [ ] **Kometa** - Plex metadata enhancement
- [ ] **Unpackerr** - Archive extraction utility
- [ ] **Recyclarr** - Quality profile synchronization

### Phase 4: Productivity Applications
**Goal**: Migrate user-facing productivity and content management tools

#### 4.1 Photo Management
- [ ] **Immich** - Photo and video management
  - Deploy PostgreSQL with vector extensions
  - Deploy Redis for caching
  - Deploy machine learning service for AI features
  - Mount existing `/mnt/user/photos/immich` for photos
  - Use Rook Ceph for thumbnails and optimized storage
  - Test photo upload, ML processing, and sharing

#### 4.2 Documentation & Knowledge
- [ ] **BookStack** - Wiki and documentation platform
  - Deploy MariaDB StatefulSet
  - Configure for existing documentation
  - Test page creation and user management


### Phase 5: Utilities & Enhancement
**Goal**: Deploy supporting tools and monitoring

#### 5.1 Monitoring & Dashboards
- [ ] **Uptime Kuma** - Service uptime monitoring
  - Configure to monitor both legacy and new services
  - Set up alerting for service failures
  - Test notification channels

- [ ] **Homer** - Homepage dashboard
  - Configure service discovery for Kubernetes services
  - Update service links and categories
  - Customize for new infrastructure

#### 5.2 Specialized Tools
- [ ] **Czkawka** - Duplicate file finder
  - Configure for media and photo directories
  - Schedule periodic scans via CronJob
  - Test duplicate detection across NFS mounts

#### 5.3 AI/ML Services (Optional)
- [ ] **LiteLLM** - LLM proxy and gateway
  - Configure for multiple LLM providers
  - Test API proxying and rate limiting
  - Integrate with other services if needed

### Phase 6: Migration Completion
**Goal**: Finalize migration and optimize deployment

#### 6.1 Service Optimization
- [ ] Review resource allocation and adjust limits/requests
- [ ] Implement horizontal pod autoscaling where appropriate
- [ ] Optimize storage usage and performance
- [ ] Fine-tune network policies and security

#### 6.2 Backup & Disaster Recovery
- [ ] Implement comprehensive backup strategy for PVCs
- [ ] Test backup restoration procedures
- [ ] Document disaster recovery processes
- [ ] Schedule regular backup validation

#### 6.3 Legacy Cleanup
- [ ] Verify all services are functioning correctly in Kubernetes
- [ ] Update external monitoring and alerting
- [ ] Decommission SWAG reverse proxy on Nezuko
- [ ] Archive or remove legacy Docker Compose configurations

## Service-Specific Considerations

### High-Complexity Migrations

#### qBittorrent (VPN Integration)
- **Challenge**: Requires VPN connectivity for all traffic
- **Solution**: VPN sidecar container or cluster-wide VPN integration
- **Testing**: Verify IP address masking and torrent connectivity

#### AdGuard Home (Host Networking)
- **Challenge**: Needs UDP port 53 for DNS
- **Solution**: Host networking or LoadBalancer service
- **Testing**: Verify DNS resolution for cluster and external clients

#### Authentik (Critical Dependency)
- **Challenge**: Many services depend on this for authentication
- **Solution**: Deploy early with comprehensive testing
- **Testing**: Verify OIDC integration with test applications

#### Plex (Hardware Acceleration)
- **Challenge**: Intel GPU access for transcoding
- **Solution**: Device plugins or node affinity for Intel NUCs
- **Testing**: Verify hardware transcoding and stream quality

### Multi-Service Applications

#### LibreChat (Skipped)
- **Rationale**: No longer actively used
- **Action**: Archive configuration, skip migration

#### Media Stack Interdependencies
- **Challenge**: 13 services with complex networking and shared storage
- **Solution**: Deploy in coordinated phases with shared PVCs
- **Testing**: Verify end-to-end automation pipeline

#### Immich Components
- **Strategy**: Deploy as service group with shared storage strategy
- **Dependencies**: PostgreSQL → Redis → Server → ML → Client access

## Resource Requirements

### Storage Allocation
- **Rook Ceph**: All available local storage per node
- **NFS Mounts**: Read-only for media, read-write for active directories
- **Backup Storage**: Separate backup target (external or cloud)

### Compute Requirements
- **Database Services**: Higher memory allocation, persistent storage
- **Media Processing**: CPU-intensive, potential GPU acceleration
- **Web Applications**: Standard web service resource patterns

### Network Requirements
- **Internal Communication**: Cluster networking for service-to-service
- **External Access**: Ingress through gateway with external-dns
- **VPN Integration**: Secure overlay for torrent traffic

## Success Criteria

### Phase Completion Gates
- [ ] All services in phase are healthy and accessible
- [ ] Data integrity verified (no data loss during migration)
- [ ] Performance meets or exceeds legacy system
- [ ] Monitoring and alerting functional
- [ ] Backup and recovery procedures tested

### Overall Migration Success
- [ ] All production services migrated and operational
- [ ] Service availability maintained throughout migration
- [ ] New Kubernetes infrastructure is maintainable and scalable
- [ ] Documentation complete for ongoing operations
- [ ] Team knowledge transfer completed

## Rollback Procedures

### Service-Level Rollback
- Revert DNS records to point back to Nezuko SWAG
- Maintain Nezuko services until Kubernetes migration confirmed stable
- Use subdomain testing to minimize production impact

### Phase-Level Rollback
- Document known-good configurations before each phase
- Maintain ability to quickly redeploy previous phase state
- Keep legacy services running until next phase validation

### Emergency Procedures
- Immediate DNS failover to legacy infrastructure
- Critical service recovery procedures documented
- Contact information and escalation procedures defined

## Timeline Estimates

- **Phase 1 (Infrastructure)**: 1-2 weeks
- **Phase 2 (Authentication/Core)**: 1-2 weeks
- **Phase 3 (Media Infrastructure)**: 2-3 weeks
- **Phase 4 (Productivity Apps)**: 2-3 weeks
- **Phase 5 (Utilities)**: 1 week
- **Phase 6 (Optimization)**: 1 week

**Total Estimated Duration**: 8-12 weeks with learning and testing time

## Next Steps

1. **Review and approve** this migration plan
2. **Begin Phase 1** with Rook Ceph deployment
3. **Establish** weekly progress reviews and checkpoint meetings
4. **Create** detailed service-specific migration procedures as needed
5. **Set up** monitoring and alerting for migration progress
