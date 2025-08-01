# DNS Architecture for Kubernetes Migration

## Context and Background

This document captures a comprehensive architectural discussion about redesigning DNS infrastructure for a homelab Kubernetes cluster during a Docker-to-Kubernetes migration period.

### Current Infrastructure

**Network Setup**:
- Network: `192.168.1.0/24`
- Gateway: `192.168.1.1` (UniFi Dream Machine Pro - UDMP)
- Domain: `$(SECRET_DOMAIN}` (managed by Cloudflare)
- Migration source: Docker Compose stack on Nezuko (`192.168.1.58`)
- Kubernetes cluster: 3-node Talos cluster

**Current DNS Services**:
- **k8s-gateway** at `192.168.1.71`: External Kubernetes resource resolution
- **CoreDNS** (internal): Cluster DNS resolution (`cluster.local`)
- **External-DNS** (Cloudflare): Public internet DNS record management

**Gateway IPs**:
- `192.168.1.72`: Internal gateway (LAN access)
- `192.168.1.73`: External gateway (WAN/Cloudflare tunnel access)

## Problem Statement

### Migration Requirements

1. **Service Priority**: If a service exists in Kubernetes → resolve to `.72` or `.73`
2. **Fallback Behavior**: If service doesn't exist in Kubernetes → resolve to `.58` (Nezuko)
3. **Local Device Resolution**: `*.lan.$(SECRET_DOMAIN}` should resolve via UDMP
4. **Ad-blocking**: Home devices should get ad-blocking, pods should bypass it
5. **High Availability**: DNS should survive single node failures

### Current Limitations

- **k8s-gateway**: No fallback mechanism for unknown subdomains
- **UDMP**: No native wildcard A record support (`*.domain.com`)
- **AdGuard Home**: DNS rewrites processed before upstreams (blocks migrated services)
- **AdGuard Home**: Load balancing between upstreams, not strict fallback

## Research Findings

### UniFi Dream Machine Pro DNS Capabilities

**Confirmed Limitations**:
- Uses dnsmasq as DNS backend
- "Wildcard and duplicate CNAME records are not supported"
- No RFC 2136 dynamic DNS update support
- No TSIG authentication support
- Wildcard A records require complex workarounds that get overwritten

**Supported Features**:
- Host (A) records, Host (AAAA) records, Alias (CNAME) records
- Basic DNS record management via UniFi API
- External-DNS integration via `external-dns-unifi-webhook`

### AdGuard Home DNS Processing

**Processing Order**:
- DNS rewrites processed **BEFORE** upstream queries
- Wildcard rewrites (`*.$(SECRET_DOMAIN} → .58`) would block migrated services
- Multiple upstreams use **load balancing**, not strict fallback
- No support for "try server A, fallback to server B if no record found"

### Alternative DNS Solutions

**Technitium DNS Server** (Recommended):
- "Robust conditional forwarder zone support with unlimited options"
- "Advanced features like DNS server HTTP API and extended DNS errors support"
- Native wildcard A record support
- API-based record management
- Superior conditional forwarding vs AdGuard Home

**Blocky DNS Server** (2024 Alternative):
- "Advanced upstream DNS server configuration"
- "Network-wide ad-blocking with conditional forwarding support"
- "Highly available deployment with Redis integration"

## Recommended Architecture: Technitium DNS

### Core Design

```
Home devices → Technitium DNS (.71) → Intelligent conditional forwarding/zone resolution
```

### DNS Resolution Flow

**L1/L2 Network Flow**:
```
192.168.X.Y (home device)
    ↓ DNS Query
192.168.1.71 (Technitium LoadBalancer VIP)
    ↓ Enter cluster network
Technitium Pod
    ↓ Decision logic (see below)
    ↓ Exit cluster for forwards OR return local zone data
```

**Decision Logic**:
- **A) `device.lan.$(SECRET_DOMAIN}`**: Conditional forwarder → `192.168.1.1` (UDMP)
- **B) `foo.$(SECRET_DOMAIN}`** (exists in K8s): Zone lookup → Specific A record (gateway IP determined by HTTPRoute parentRefs)
- **C) `unknown.$(SECRET_DOMAIN}`** (not in K8s): Zone lookup → Wildcard A record (`.58`)
- **D) `google.com`**: Upstream forwarder → `1.1.1.1, 8.8.8.8`

### HTTPRoute Gateway Selection

**Gateway IP Assignment**:
- HTTPRoutes with `parentRefs: external` → External-DNS creates record pointing to `.73`
- HTTPRoutes with `parentRefs: internal` → External-DNS creates record pointing to `.72`
- Both internal and external devices get the same IP - no DNS-based short-circuiting

### Technitium Configuration

**DNS Zone**: `$(SECRET_DOMAIN}`
```
Zone: $(SECRET_DOMAIN}
├── *.$(SECRET_DOMAIN} → 192.168.1.58 (wildcard fallback)
├── foo.$(SECRET_DOMAIN} → 192.168.1.72 (specific record - overrides wildcard)
└── bar.$(SECRET_DOMAIN} → 192.168.1.73 (specific record - overrides wildcard)
```

**Conditional Forwarders**:
```
lan.$(SECRET_DOMAIN} → 192.168.1.1 (UDMP for local devices)
```

**Upstream DNS**:
```
Default: 1.1.1.1, 8.8.8.8
```

### Kubernetes Configuration

**Technitium Deployment**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: technitium-dns
spec:
  replicas: 2  # HA deployment
  template:
    spec:
      containers:
      - name: technitium
        image: technitium/dns-server
        ports:
        - containerPort: 53
          protocol: UDP
        - containerPort: 53
          protocol: TCP
        - containerPort: 5380  # Web UI
        volumeMounts:
        - name: data
          mountPath: /etc/dns
```

**LoadBalancer Service**:
```yaml
apiVersion: v1
kind: Service
metadata:
  name: technitium-dns
  annotations:
    lbipam.cilium.io/ips: "192.168.1.71"
spec:
  type: LoadBalancer
  ports:
  - name: dns-udp
    port: 53
    protocol: UDP
  - name: dns-tcp
    port: 53
    protocol: TCP
  - name: web-ui
    port: 5380
    protocol: TCP
```

**External-DNS Integration** (if webhook available):
```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: technitium-dns-external
spec:
  values:
    provider:
      name: webhook  # or API-based integration
      webhook:
        env:
        - name: TECHNITIUM_HOST
          value: http://technitium-dns.default.svc.cluster.local:5380
        - name: TECHNITIUM_API_TOKEN
          valueFrom:
            secretKeyRef:
              name: technitium-secret
              key: api-token
    sources: ["gateway-httproute", "service"]
    domainFilters: ["$(SECRET_DOMAIN}"]
```

### Migration Workflow

**Service Migration Process**:
1. **Deploy K8s service**: Create HTTPRoute/Service in cluster
2. **External-DNS detects**: HTTPRoute creation triggers external-dns
3. **API call**: External-DNS calls Technitium API to create specific A record
4. **DNS resolution**: Specific record overrides wildcard, resolves to `.72/.73`
5. **Traffic flows**: Home devices connect to Kubernetes service

**Post-Migration Cleanup**:
1. Remove wildcard A record: `*.$(SECRET_DOMAIN} → .58`
2. Keep specific records created by external-dns
3. Clean unused Docker Compose configurations

## Pod DNS Configuration (Unchanged)

**Internal CoreDNS** remains completely separate:
- **Service IP**: `10.43.0.10` (ClusterIP)
- **Purpose**: `*.cluster.local`, `*.svc.cluster.local` resolution
- **Forward plugin**: `parameters: . /etc/resolv.conf` (direct to upstream DNS)
- **No interaction**: Pods bypass home network DNS entirely

## Ad-blocking Integration Options

### Option 1: Separate AdGuard Home
```
Home devices → Technitium (.71) → Forward filtered queries → AdGuard Home
```

### Option 2: Technitium with Blocky
```
Home devices → Blocky (.71) → Ad-blocking + conditional forwarding
```

### Option 3: Router-level filtering
```
Home devices → Technitium (.71) → Router forwards to filtered upstream
```

## External DNS Services (Unchanged)

**Cloudflare External-DNS**:
- **Purpose**: Public internet DNS records
- **Sources**: `["crd", "gateway-httproute"]`
- **Target**: Cloudflare public DNS servers
- **Flow**: Internet users → Cloudflare DNS → Cloudflare proxy → `.73` external gateway

## Configuration Responsibilities

### Technitium DNS Server
- DNS zone management (`$(SECRET_DOMAIN}`)
- Wildcard and specific A records
- Conditional forwarders configuration
- API/webhook endpoints for automation
- Upstream DNS server configuration

### Kubernetes Cluster
- Technitium deployment and service configuration
- LoadBalancer VIP assignment (`.71`)
- External-DNS webhook/API integration
- Persistent storage for DNS data
- HTTPRoute/Service definitions that trigger DNS record creation

### UDMP Router
- Local device hostname resolution (`*.lan.$(SECRET_DOMAIN}`)
- DHCP DNS server assignment (point to `.71`)
- External-DNS unifi-webhook integration (existing)

## Benefits of This Architecture

1. **Intelligent Fallback**: Native wildcard → specific record override behavior
2. **Migration-Friendly**: Gradual service migration with automatic DNS updates
3. **Minimal Complexity**: Single DNS decision point with proven technology
4. **Future-Proof**: API-based automation and GitOps integration
5. **High Availability**: Multi-replica deployment with LoadBalancer VIP
6. **Clean Separation**: Pod DNS completely separate from home network DNS

## Alternative Considerations

### Blocky DNS Alternative
- Modern Go-based DNS server (2024)
- Built-in ad-blocking capabilities
- Redis-backed HA deployments
- Advanced upstream configuration

### Keep Current Architecture
- Rely on external-dns + UDMP for specific records
- Accept that unknown subdomains fail (no fallback)
- Manually manage migration DNS records

## Final Architecture Summary

### Corrected Understanding

**HTTPRoute Determines Gateway**: Services specify `parentRefs: external` (→ .73) or `parentRefs: internal` (→ .72)
**DNS Returns Same IP**: Both internal and external clients get the same resolved IP
**No Short-Circuiting**: Internal devices connect directly to the designated gateway IP
**Gateway Selection**: Determined by HTTPRoute configuration, not DNS resolution path

### Updated Traffic Flows

**Internal Client to External Service** (e.g., home.$(SECRET_DOMAIN}):
```
MacBook → Technitium (.71) → Returns .73 → Direct connection to .73 → K8s external gateway
```

**External Client to External Service**:
```
Android → Cloudflare DNS → Returns Cloudflare IPs → Tunnel → .73 → K8s external gateway
```

**Both reach the same .73 gateway** - difference is routing path, not destination IP.

## Migration Timeline

**Phase 1**: Deploy Technitium with wildcard fallback
**Phase 2**: Configure external-dns integration for automated record creation
**Phase 3**: Migrate services individually (DNS automatically updated)
**Phase 4**: Remove wildcard fallback and manual Cloudflare wildcard after migration complete

## Key Decision Points

1. **DNS Server Choice**: Technitium vs Blocky vs AdGuard Home
2. **External-DNS Integration**: API-based vs webhook-based vs manual
3. **Ad-blocking Integration**: Separate service vs integrated solution
4. **High Availability**: Single vs multi-replica deployment

This architecture provides the intelligent conditional forwarding with fallback behavior that AdGuard Home cannot deliver, while maintaining the proven external-dns automation pattern from the community.

## Implementation Update (2025-08-01)

### New Requirements
- **UI Access**: Use internal HTTPRoute gateway for web UI access initially
- **Subdomain**: Use `dns.$(SECRET_DOMAIN}` (replacing legacy AdGuard Home)
- **Deployment Location**: `kubernetes/apps/network/technitium-dns/`
- **Automation**: Leverage Technitium HTTP API for initial configuration

### Technitium API Capabilities
Based on API documentation analysis, Technitium provides comprehensive HTTP API for:
- **Authentication**: Non-expiring API tokens (`/api/user/createToken`)
- **Zone Management**: Create/manage DNS zones (`/api/zones/create`, `/api/zones/records/add`)
- **Conditional Forwarding**: Configure forwarders and upstream DNS
- **All Settings**: Complete parity with web console functionality

**Key API Endpoints for Architecture**:
```bash
# Authentication
POST /api/user/createToken?user=admin&pass=admin&tokenName=k8s-setup

# Create primary zone
POST /api/zones/create?zone=$(SECRET_DOMAIN}&type=Primary

# Add wildcard fallback
POST /api/zones/records/add?zone=$(SECRET_DOMAIN}&type=A&name=*&rdata=192.168.1.58

# Conditional forwarder for local devices
POST /api/zones/create?zone=lan.$(SECRET_DOMAIN}&type=Forwarder&forwarder=192.168.1.1

# Configure upstream DNS
POST /api/settings/setDnsSettings?forwarders=1.1.1.1,8.8.8.8
```

### Deployment Configuration
**HTTPRoute Configuration**:
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: technitium-dns
spec:
  parentRefs:
  - name: internal  # Internal gateway initially
  hostnames:
  - dns.$(SECRET_DOMAIN}
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: technitium-dns
      port: 5380
```

**LoadBalancer Service**:
```yaml
apiVersion: v1
kind: Service
metadata:
  name: technitium-dns-lb
  annotations:
    lbipam.cilium.io/ips: "192.168.1.71"
spec:
  type: LoadBalancer
  ports:
  - name: dns-udp
    port: 53
    protocol: UDP
  - name: dns-tcp
    port: 53
    protocol: TCP
```

### Automation Strategy
1. **Init Container**: Use curl/jq container to call API post-deployment
2. **ConfigMap Script**: Store API setup commands as executable script
3. **Secret Management**: Store API credentials in SOPS-encrypted secret
4. **Idempotent Setup**: Design scripts to be re-runnable safely

### Affected Areas Analysis (2025-08-01)

**Critical IP Address Conflict**:
- Current: k8s-gateway uses `192.168.1.71` at `kubernetes/apps/network/k8s-gateway/app/helmrelease.yaml:41`
- Plan: Technitium needs `192.168.1.71` to replace k8s-gateway functionality
- Impact: k8s-gateway must be reconfigured or decommissioned

**DNS Subdomain Replacement**:
- Current: AdGuard Home uses `dns.$(SECRET_DOMAIN}` (referenced in Homer dashboard at line 113-116)
- Plan: Technitium will take over `dns.$(SECRET_DOMAIN}` subdomain
- Impact: Homer dashboard needs updating, AdGuard Home needs decommissioning

**External-DNS Integration**:
- Current: Cloudflare external-dns only watches `external` gateway HTTPRoutes (line 39)
- Plan: May need additional external-dns instance or webhook for Technitium zone management
- Impact: Current external-dns setup is compatible but doesn't automate Technitium records

**Network Architecture**:
- Current Gateways: Internal (192.168.1.72), External (192.168.1.73)
- Current DNS: k8s-gateway (192.168.1.71), CoreDNS (10.43.0.10)
- Plan: Technitium replaces k8s-gateway at 192.168.1.71

**Available Resources**:
- App-template: bjw-s 4.1.2 available at `kubernetes/components/common/repos/app-template/`
- Network namespace: Existing at `kubernetes/apps/network/`
- HTTPRoute pattern: Well-established in cluster

## Current Implementation Plan

### Phase 1: Core Technitium Deployment
1. **Create Technitium deployment structure**:
   - `kubernetes/apps/network/technitium-dns/ks.yaml` - Kustomization reference
   - `kubernetes/apps/network/technitium-dns/app/helmrelease.yaml` - Main deployment using bjw-s app-template
   - `kubernetes/apps/network/technitium-dns/app/kustomization.yaml` - App resources
   - `kubernetes/apps/network/technitium-dns/app/resources/pvc.yaml` - Persistent storage
   - `kubernetes/apps/network/technitium-dns/app/resources/service.yaml` - LoadBalancer service
   - `kubernetes/apps/network/technitium-dns/app/resources/httproute.yaml` - Internal gateway access

2. **Configure services**:
   - DNS LoadBalancer: `192.168.1.71` (replacing k8s-gateway)
   - Web UI: `dns.$(SECRET_DOMAIN}` via internal HTTPRoute
   - Persistent storage: 1Gi for DNS data
   - Security: Non-root user, read-only filesystem where possible

### Phase 2: RFC 2136 Dynamic DNS Setup
1. **Manual Technitium configuration**:
   - Initial admin password change (web UI)
   - Create TSIG key for external-dns (Settings → TSIG, HMAC-SHA256)
   - Enable Dynamic Updates (RFC2136) for `$(SECRET_DOMAIN}` zone
   - Configure Security Policy allowing external-dns key to update records

2. **Configure zones via API**:
   - Primary zone: `$(SECRET_DOMAIN}`
   - Wildcard fallback: `*.$(SECRET_DOMAIN} → 192.168.1.58`
   - Conditional forwarder: `lan.$(SECRET_DOMAIN} → 192.168.1.1`
   - Upstream DNS: `1.1.1.1, 8.8.8.8`

### Phase 3: Dual External-DNS Architecture
1. **Keep existing cloudflare-dns (unchanged)**:
   ```yaml
   provider: cloudflare
   gateway-name: external
   sources: ["crd", "gateway-httproute"]
   # Creates Cloudflare records for external HTTPRoutes only
   ```

2. **Add new technitium-external-dns**:
   ```yaml
   provider: rfc2136
   gateway-name: internal,external  # Watch both gateways
   rfc2136-host: technitium-dns.network.svc.cluster.local
   rfc2136-tsig-keyname: external-dns
   rfc2136-tsig-secret: <SOPS-encrypted>
   # Creates Technitium records for all HTTPRoutes
   ```

3. **Create SOPS-encrypted secret**:
   - Store TSIG key securely
   - Reference in external-dns deployment

### Phase 4: k8s-gateway Decommission
1. **Test DNS resolution**: Verify both external and internal services resolve
2. **Update UDMP DNS**: Point to `192.168.1.71` (Technitium)
3. **Remove k8s-gateway**: Delete entire directory and kustomization reference
4. **Update Homer dashboard**: Change AdGuard entry to Technitium DNS

### Record Creation Logic (Final State)
- **External HTTPRoute** (`parentRefs: external`):
  - Cloudflare: `service.$(SECRET_DOMAIN} → 192.168.1.73` (internet access)
  - Technitium: `service.$(SECRET_DOMAIN} → 192.168.1.73` (local access)
- **Internal HTTPRoute** (`parentRefs: internal`):
  - Technitium only: `service.$(SECRET_DOMAIN} → 192.168.1.72` (local only)

### Manual Setup Required
- **Initial admin password change**: Must be done via web UI first login
- **TSIG key creation**: Generate via Technitium web UI (Settings → TSIG)
- **Dynamic Updates enable**: Configure via web UI (Zone → Dynamic Updates)
- **Security Policy setup**: Define allowed record types and domains
- **DNS testing**: Verify resolution and fallback behavior

### Files to Create/Modify
- `kubernetes/apps/network/technitium-dns/` - Complete deployment structure
- `kubernetes/apps/network/technitium-external-dns/` - New external-dns instance
- `kubernetes/apps/network/kustomization.yaml` - Add technitium references, remove k8s-gateway
- `kubernetes/apps/default/homer/app/config/config.yml` - Update DNS entry
- Remove: `kubernetes/apps/network/k8s-gateway/` (entire directory)

### Rollback Plan
- Keep k8s-gateway deployment ready
- Maintain UDMP DNS backup configuration
- Document IP address changes for quick reversion

## Implementation Update (2025-08-01) - Final Research

### Technitium Clustering Limitations Research
Based on extensive research of official documentation and community experiences:

**Database Backend Reality**:
- **No database backend for core DNS data**: Zone data remains file-based, not database-backed
- **Database support limited to**: Query logging only (SQLite, MySQL, MS SQL - NOT PostgreSQL)
- **File-based storage implications**: Each instance maintains separate state, requires DNS zone transfers for replication

**High Availability Current Status**:
- **No native clustering**: Multiple replicas with shared database state not supported
- **Community evidence**: "Native clustering has been 'coming in a few months' for 2+ years"
- **Kubernetes challenges**: Shared PVC causes data corruption and config conflicts between replicas
- **Production workarounds**: Single instance with external load balancing or anycast routing

**Architectural Decision**: Single-Instance with Fast Failover
- **Fast failover configuration**: Recreate strategy, aggressive health probes, system-critical priority
- **VIP resilience**: Cilium LoadBalancer ensures 192.168.1.71 follows service across nodes
- **Future expansion**: Zone transfer-based replication when clustering becomes available

### Version and Resilience Requirements
**Fixed version**: `technitium/dns-server:13.6.0` (not latest)
**Fast failover requirements**:
- Pod recovers on new node within ~30 seconds of failure
- VIP automatically migrates regardless of node failures
- Critical scheduling priority for guaranteed placement
- Aggressive health probe timing for rapid failure detection

### Updated Implementation Approach
**Single resilient instance** designed for maximum Kubernetes availability:
- Strategy: Recreate with fast termination (5s grace period)
- Priority: system-cluster-critical for scheduling guarantees
- Health probes: HTTP-based (no executable commands) with aggressive timing
- Storage: Dedicated PVC per instance (no sharing to avoid corruption)
- Resource requests: Ensure reliable node placement under load

**RFC2136 External-DNS Integration**:
- Confirmed working pattern from community examples (rwlove/home-ops)
- TSIG key authentication with SOPS encryption
- Watch both internal/external HTTPRoutes for comprehensive automation
- Target: 192.168.1.71:53 (Technitium LoadBalancer VIP)

### Migration Phases (Finalized)
1. **Memory bank update** with research findings and architectural decisions
2. **Resilient single-instance deployment** with fast failover configuration
3. **RFC2136 external-dns setup** for automated Kubernetes service DNS records
4. **Manual configuration** via web UI (admin password, TSIG key, zones)
5. **Infrastructure migration** (UDMP DNS settings, k8s-gateway removal)

This approach provides reliable DNS service with maximum Kubernetes resilience while positioning for future native clustering when available.
