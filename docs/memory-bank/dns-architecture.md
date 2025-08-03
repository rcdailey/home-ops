# DNS Architecture for Kubernetes Migration

## Overview

This document consolidates the complete DNS architecture for a homelab Kubernetes cluster during Docker-to-Kubernetes migration. It covers architectural decisions, implementation status, troubleshooting insights, and operational procedures.

## Current Infrastructure Status (2025-08-02)

### Network Architecture
- **Network**: `192.168.1.0/24`
- **Gateway**: `192.168.1.1` (UniFi Dream Machine Pro - UDMP)
- **Domain**: `${SECRET_DOMAIN}` (managed by Cloudflare)
- **Migration source**: Docker Compose stack on Nezuko (`192.168.1.58`)
- **Kubernetes cluster**: 3-node Talos cluster

**Gateway IPs**:
- **DNS Gateway**: `192.168.1.71` (Technitium DNS via LoadBalancer)
- **Internal Gateway**: `192.168.1.72` (Envoy Gateway - LAN services)
- **External Gateway**: `192.168.1.73` (Envoy Gateway - WAN/tunnel services)

### Current DNS Services
- **Technitium DNS** (`192.168.1.71`): Primary DNS with provider-agnostic infrastructure
- **CoreDNS** (internal): Cluster DNS resolution (`*.cluster.local`)
- **Cloudflare External-DNS**: Public internet DNS record management
- **Technitium External-DNS**: Internal service DNS automation (configured, pending deployment)

## Architecture Components

### DNS Resolution Flow

**L1/L2 Network Flow**:
```
192.168.X.Y (home device)
    ↓ DNS Query
192.168.1.71 (dns-gateway LoadBalancer VIP)
    ↓ Routes to DNS provider
Technitium Pod (component: dns-server)
    ↓ Decision logic
    ↓ Returns appropriate resolution
```

**Decision Logic**:
- **A) `device.lan.${SECRET_DOMAIN}`**: Conditional forwarder → `192.168.1.1` (UDMP)
- **B) `foo.${SECRET_DOMAIN}`** (exists in K8s): Zone lookup → Gateway IP via External-DNS
- **C) `unknown.${SECRET_DOMAIN}`** (not in K8s): Wildcard A record → `192.168.1.58` (fallback)
- **D) `google.com`**: Upstream forwarder → `1.1.1.1, 8.8.8.8`

### Migration Requirements

1. **Service Priority**: If a service exists in Kubernetes → resolve to `.72` or `.73`
2. **Fallback Behavior**: If service doesn't exist in Kubernetes → resolve to `.58` (Nezuko)
3. **Local Device Resolution**: `*.lan.${SECRET_DOMAIN}` should resolve via UDMP
4. **Ad-blocking**: Home devices should get ad-blocking, pods should bypass it
5. **High Availability**: DNS should survive single node failures

## Completed Implementations ✅

### 1. Gateway & External-DNS Architecture

**Issue Resolved**: External-DNS created A records from Gateway LoadBalancer IPs instead of CNAMEs
**Solution**: Target annotation inheritance pattern

```yaml
# Gateway configuration (inheritance source)
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  annotations:
    external-dns.alpha.kubernetes.io/target: external.${SECRET_DOMAIN}  # external gateway
    external-dns.alpha.kubernetes.io/target: internal.${SECRET_DOMAIN}  # internal gateway

# HTTPRoute configuration (inherits from Gateway)
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-service
  # NO target annotation - inherits from Gateway
spec:
  parentRefs:
  - name: external  # Inherits external.${SECRET_DOMAIN}
```

**Benefits**:
- CNAME-only DNS records (no A records from Gateway IPs)
- Cloudflare tunnel compatibility restored
- Automatic inheritance (impossible to deploy HTTPRoute without target)
- Zero-downtime service migrations

### 2. App-Template Route Field Migration

**Implementation**: Consolidated routing configuration with application config

**Before**: Separate HTTPRoute files
```yaml
# Separate file: app/httproute.yaml
kind: HTTPRoute
metadata:
  annotations:
    external-dns.alpha.kubernetes.io/target: external.${SECRET_DOMAIN}
```

**After**: App-template route field
```yaml
# In HelmRelease values:
route:
  app:
    hostnames: ["service.${SECRET_DOMAIN}"]
    parentRefs:
    - name: external
      namespace: network
      sectionName: https
    # Inherits target from external gateway
```

**Results**:
- Eliminated 3 standalone HTTPRoute files (50% reduction)
- Co-located routing config with application config
- Consistent app-template patterns across services

### 3. DNS Gateway Infrastructure Separation

**Issue**: DNS server application (Technitium) coupled with DNS infrastructure service
**Impact**: DNS provider migration would cause downtime

**Solution**: Component-based service architecture
```yaml
# Infrastructure: dns-gateway service
apiVersion: v1
kind: Service
metadata:
  name: dns-gateway
  annotations:
    lbipam.cilium.io/ips: "192.168.1.71"
spec:
  type: LoadBalancer
  selector:
    app.kubernetes.io/component: dns-server  # Provider-agnostic
  ports:
  - name: dns-tcp
    port: 53
    protocol: TCP
  - name: dns-udp
    port: 53
    protocol: UDP

# Application: technitium-dns
controllers:
  technitium-dns:
    labels:
      app.kubernetes.io/component: dns-server  # Connects to dns-gateway
```

**Migration Benefits**:
- Zero-downtime DNS provider switching capability
- Infrastructure/application separation achieved
- Future Blocky/other DNS provider support ready

## Current Implementation Status

### Technitium DNS Server

**Deployment Configuration**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: technitium-dns
spec:
  replicas: 1  # Single instance due to clustering limitations
  template:
    spec:
      containers:
      - name: technitium
        image: technitium/dns-server:13.6.0  # Fixed version
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
  name: dns-gateway
  annotations:
    lbipam.cilium.io/ips: "192.168.1.71"
spec:
  type: LoadBalancer
  selector:
    app.kubernetes.io/component: dns-server
  ports:
  - name: dns-udp
    port: 53
    protocol: UDP
  - name: dns-tcp
    port: 53
    protocol: TCP
```

**HTTPRoute for Web UI**:
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: technitium-dns
spec:
  parentRefs:
  - name: internal  # Internal gateway access
  hostnames:
  - dns.${SECRET_DOMAIN}
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: technitium-dns
      port: 5380
```

### Technitium Configuration

**DNS Zone**: `${SECRET_DOMAIN}`
```
Zone: ${SECRET_DOMAIN}
├── *.${SECRET_DOMAIN} → 192.168.1.58 (wildcard fallback)
├── foo.${SECRET_DOMAIN} → 192.168.1.72 (specific record - overrides wildcard)
└── bar.${SECRET_DOMAIN} → 192.168.1.73 (specific record - overrides wildcard)
```

**Conditional Forwarders**:
```
lan.${SECRET_DOMAIN} → 192.168.1.1 (UDMP for local devices)
```

**Upstream DNS**:
```
Default: 1.1.1.1, 8.8.8.8
```

### Technitium API Capabilities

**Key API Endpoints for Architecture**:
```bash
# Authentication
POST /api/user/createToken?user=admin&pass=admin&tokenName=k8s-setup

# Create primary zone
POST /api/zones/create?zone=${SECRET_DOMAIN}&type=Primary

# Add wildcard fallback
POST /api/zones/records/add?zone=${SECRET_DOMAIN}&type=A&name=*&rdata=192.168.1.58

# Conditional forwarder for local devices
POST /api/zones/create?zone=lan.${SECRET_DOMAIN}&type=Forwarder&forwarder=192.168.1.1

# Configure upstream DNS
POST /api/settings/setDnsSettings?forwarders=1.1.1.1,8.8.8.8
```

## External-DNS Architecture Investigation (2025-08-04) 🔄

### Problem Analysis

**Original Issue**: Dual external-dns instances with overlapping sources caused DNS record deletion crisis when Cloudflare external-dns deleted all HTTPRoute records due to txtOwnerId conflicts.

**Root Cause Research**: External-dns filtering limitations discovered through comprehensive investigation:

1. **Label-filter applies globally**: `--label-filter` affects ALL sources in an external-dns instance, not specific source types
2. **Cross-source filtering impossible**: Cannot apply different filters to CRDs vs HTTPRoutes in same instance
3. **Annotation-filter issues**: Client-side filtering with known DNSEndpoint bugs (Issue #3634)

### Attempted Solutions That Failed ❌

#### Option 1: Label-based Separation (Failed)
```yaml
# Attempted configuration
sources: ["crd", "gateway-httproute"]
extraArgs: ["--label-filter=dns-provider=cloudflare"]
```
**Problem**: Label filter affects both CRDs AND HTTPRoutes, causing HTTPRoute filtering since they lack `dns-provider` labels.

#### Option 2: Domain-based Separation (Rejected)
```yaml
# Would require changing tunnel target
- dnsName: "tunnel.${SECRET_DOMAIN}"  # Instead of external.${SECRET_DOMAIN}
```
**Problem**: Breaks existing Gateway inheritance architecture where HTTPRoutes inherit `external.${SECRET_DOMAIN}` from Gateway.

#### Option 3: Annotation-based Filtering (Unsuitable)
```yaml
# Research findings
extraArgs: ["--annotation-filter=external-dns.alpha.kubernetes.io/provider=cloudflare"]
```
**Problems**:
- Client-side filtering (poor performance)
- Issue #3634: DNSEndpoints ignored when annotation-filter set
- Still applies globally across all sources

### Crisis Event: Cloudflare Record Deletion

**Timeline (2025-08-04)**:
1. Added `--label-filter=dns-provider=cloudflare` to Cloudflare external-dns
2. Cloudflare external-dns could no longer see HTTPRoutes (no `dns-provider` labels)
3. External-dns deleted all previously managed HTTPRoute DNS records
4. Services became inaccessible via Cloudflare tunnel

**Records Deleted**: home.dailey.app, torrent-test.dailey.app, flux-webhook.dailey.app, echo.dailey.app, auth-test.dailey.app

**Immediate Fix Applied**:
- Removed `--label-filter=dns-provider=cloudflare` from Cloudflare external-dns
- Changed `txtOwnerId: default` to `txtOwnerId: cloudflare` for clearer ownership

### Current Configuration Issues

**Cloudflare External-DNS**:
```yaml
sources: ["crd", "gateway-httproute"]
extraArgs: ["--gateway-name=external"]  # HTTPRoute filtering
txtOwnerId: cloudflare
# No CRD filtering - processes ALL DNSEndpoints
```

**Technitium External-DNS**:
```yaml
sources: ["crd", "gateway-httproute"]
extraArgs: ["--label-filter=dns-provider=technitium"]  # CRD filtering
txtOwnerId: technitium
# No HTTPRoute filtering - processes ALL HTTPRoutes
```

**Current Problem**: Both instances process DNSEndpoints without proper separation.

### Proposed Solution: 4-Instance Architecture 🎯

**Research-Based Recommendation**: Deploy separate external-dns instances for different source types, following external-dns FAQ guidance: "If you need to filter only one specific source you have to run a separated external dns service."

#### Instance Architecture

| Instance | Directory | Sources | Filters | Purpose |
|----------|-----------|---------|---------|---------|
| `cloudflare-dns` | `cloudflare-dns/` | `gateway-httproute` | `--gateway-name=external` | External HTTPRoutes → Cloudflare |
| `cloudflare-dns-crd` | `cloudflare-dns-crd/` | `crd` | `--label-filter=dns-provider=cloudflare` | Cloudflare DNSEndpoints → Cloudflare |
| `technitium-external-dns` | `technitium-external-dns/` | `gateway-httproute` | None (both gateways) | All HTTPRoutes → Technitium |
| `technitium-external-dns-crd` | `technitium-external-dns-crd/` | `crd` | `--label-filter=dns-provider=technitium` | Technitium DNSEndpoints → Technitium |

#### Directory Structure (Conservative Approach)
Following existing codebase patterns (rook-ceph/operator + rook-ceph/cluster):

```
kubernetes/apps/network/
├── cloudflare-dns/                   # HTTPRoutes only
│   ├── app/helmrelease.yaml
│   └── ks.yaml
├── cloudflare-dns-crd/               # NEW - DNSEndpoints only
│   ├── app/helmrelease.yaml
│   └── ks.yaml
├── technitium-external-dns/          # HTTPRoutes only
│   ├── app/helmrelease.yaml
│   └── ks.yaml
├── technitium-external-dns-crd/      # NEW - DNSEndpoints only
│   ├── app/helmrelease.yaml
│   └── ks.yaml
```

#### Expected Results

**External HTTPRoutes** (e.g., `app.dailey.app`):
- **Cloudflare-dns**: Creates Cloudflare records (internet access via tunnel)
- **Technitium-external-dns**: Creates Technitium records (LAN access to 192.168.1.73)
- **Dual registration**: Same service accessible via both paths

**Internal HTTPRoutes** (e.g., `dns.dailey.app`):
- **Technitium-external-dns**: Creates Technitium records (LAN access to 192.168.1.72)
- **Single registration**: Internal-only services

**DNSEndpoints**:
- **Cloudflare-dns-crd**: Processes `dns-provider=cloudflare` (tunnel CNAME)
- **Technitium-external-dns-crd**: Processes `dns-provider=technitium` (Gateway A records)

### Research Citations

**External-DNS Documentation Findings**:
- "When using multiple sources, --annotation-filter will filter every given source objects"
- "If you need to filter only one specific source you have to run a separated external dns service"
- Label-filter enables server-side filtering vs annotation-filter client-side filtering
- Issue #3634: DNSEndpoints ignored when annotation-filter set unless matching annotation exists

**Performance Implications**:
- Multiple lightweight instances > single heavy instance for large clusters
- Label-filter (server-side) > annotation-filter (client-side) for performance
- Separate instances enable source-specific optimization

### Implementation Status

**Current State**: Crisis resolved, but DNSEndpoint filtering broken (both instances process all DNSEndpoints)

**Next Steps**:
1. Create two new CRD-only external-dns instances
2. Remove CRD sources from existing HTTPRoute instances
3. Test DNSEndpoint label filtering with separate instances
4. Verify HTTPRoute record restoration in Cloudflare

**Risk Mitigation**: Incremental deployment with rollback capability, separate txtOwnerId values prevent conflicts

### DNS Record Distribution (Target State)
- **External HTTPRoutes** (`parentRefs: external`) → Cloudflare DNS → Tunnel endpoint
- **Internal HTTPRoutes** (`parentRefs: internal`) → Technitium DNS → Internal gateway IP
- **Both internal and external HTTPRoutes** → Technitium DNS (local resolution)

### Target Inheritance Behavior
- **External services**: Inherit `external.${SECRET_DOMAIN}` → CNAME to tunnel
- **Internal services**: Inherit `internal.${SECRET_DOMAIN}` → CNAME to internal gateway

## Troubleshooting Insights

### Envoy Gateway Connectivity Debug (2025-08-03) ✅ RESOLVED

**Issue**: `https://dns-test.${SECRET_DOMAIN}` returns "Destination host unreachable" from Windows clients
**Root Cause**: `externalTrafficPolicy: Local` caused traffic rejection when hitting wrong Kubernetes node

#### Problem Analysis
1. **Gateway Services Created with Local Policy**: Despite global HelmRelease configuration, LoadBalancer services used `externalTrafficPolicy: Local`
2. **Traffic Distribution Issue**: Local policy only accepts traffic on nodes running the gateway pod
3. **Envoy Gateway v1.4.1 Bug**: Global `externalTrafficPolicy` configuration in HelmRelease was ignored

#### Solution Implemented
**EnvoyProxy CRD with parametersRef approach**:

```yaml
# /kubernetes/apps/network/envoy-gateway/app/envoyproxy-config.yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: EnvoyProxy
metadata:
  name: cluster-traffic-policy
  namespace: network
spec:
  provider:
    type: Kubernetes
    kubernetes:
      envoyService:
        patch:
          type: StrategicMerge
          value:
            spec:
              externalTrafficPolicy: Cluster

# Gateway configuration update
spec:
  infrastructure:
    parametersRef:
      group: gateway.envoyproxy.io
      kind: EnvoyProxy
      name: cluster-traffic-policy
```

**Results**:
- Both LoadBalancer services now have `externalTrafficPolicy: Cluster`
- Gateway connectivity restored from all network locations
- HTTP 500 errors resolved
- DNS resolution works correctly through internal gateway (.72)

#### Browser-Specific DNS Resolution Issue
**Additional Discovery**: Different browsers use different DNS resolution:
- **Firefox**: Uses local DNS → resolves to 192.168.1.72 (internal gateway)
- **Vivaldi**: Uses DNS-over-HTTPS/Cloudflare → resolves to Cloudflare tunnel endpoint

**Solution**: Configure Vivaldi to disable "Use secure DNS" or add hosts file entry for local resolution

#### Validation Commands Used
```bash
# Check EnvoyProxy CRD status
kubectl get envoyproxy cluster-traffic-policy -n network
kubectl describe envoyproxy cluster-traffic-policy -n network

# Verify externalTrafficPolicy on services
kubectl get svc -n network -l gateway.envoyproxy.io/owning-gateway-name
kubectl get svc [service-name] -n network -o yaml | rg externalTrafficPolicy

# Test connectivity
curl -v https://dns-test.dailey.app
kubectl logs -n network -l gateway.envoyproxy.io/owning-gateway-name=internal
```

### Cilium Configuration Issues

**LoadBalancer IP Pool**: Too broad - `192.168.1.0/24` instead of `192.168.1.70/28`
```yaml
spec:
  blocks:
  - cidr: 192.168.1.0/24  # Should be 192.168.1.70/28
```

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
- Wildcard rewrites (`*.${SECRET_DOMAIN} → .58`) would block migrated services
- Multiple upstreams use **load balancing**, not strict fallback
- No support for "try server A, fallback to server B if no record found"

### Technitium DNS Server

**Benefits**:
- "Robust conditional forwarder zone support with unlimited options"
- "Advanced features like DNS server HTTP API and extended DNS errors support"
- Native wildcard A record support
- API-based record management
- Superior conditional forwarding vs AdGuard Home

**Clustering Limitations**:
- **No database backend for core DNS data**: Zone data remains file-based
- **Database support limited to**: Query logging only (SQLite, MySQL, MS SQL - NOT PostgreSQL)
- **No native clustering**: Multiple replicas with shared database state not supported
- **Community evidence**: "Native clustering has been 'coming in a few months' for 2+ years"

## Migration Workflow

### Service Migration Process

1. **Deploy K8s service**: Create HTTPRoute with correct parentRefs
2. **Automatic DNS**: External-DNS detects HTTPRoute and creates records
3. **Target inheritance**: HTTPRoute inherits correct target from Gateway
4. **DNS resolution**: Specific record overrides wildcard fallback
5. **Traffic flows**: Home devices connect to appropriate gateway

### Post-Migration Cleanup

1. Remove wildcard A record: `*.${SECRET_DOMAIN} → .58`
2. Keep specific records created by external-dns
3. Clean unused Docker Compose configurations

### Future DNS Provider Migration (Technitium → Blocky)

1. **Deploy Blocky** with `app.kubernetes.io/component: dns-server` label
2. **Zero-downtime cutover**: dns-gateway automatically routes to both providers
3. **Remove Technitium label**: DNS traffic routes only to Blocky
4. **Clean removal**: Delete Technitium without DNS service interruption

## Pod DNS Configuration (Unchanged)

**Internal CoreDNS** remains completely separate:
- **Service IP**: `10.43.0.10` (ClusterIP)
- **Purpose**: `*.cluster.local`, `*.svc.cluster.local` resolution
- **Forward plugin**: `parameters: . /etc/resolv.conf` (direct to upstream DNS)
- **No interaction**: Pods bypass home network DNS entirely

## Implementation Priorities

### High Priority 🔴
1. **Complete Technitium External-DNS deployment** (Kustomization issue resolution)
2. **Manual Technitium configuration** (TSIG key, zones, security)
3. **RFC2136 integration testing** (External-DNS → Technitium automation)
4. **Fix Cilium LoadBalancer IP pool** (restrict to `192.168.1.70-79`)

### Medium Priority 🟡
1. **Wildcard fallback configuration** (`*.${SECRET_DOMAIN} → 192.168.1.58`)
2. **UDMP DNS server update** (point home devices to `192.168.1.71`)
3. **k8s-gateway decommissioning** (IP address migration)

### Low Priority 🟢
1. **Ad-blocking integration** (separate service vs integrated solution)
2. **DNS provider evaluation** (Blocky alternative assessment)
3. **High availability enhancement** (when clustering becomes available)

## Manual Setup Required

### Technitium Web UI Setup
1. **Admin password change** via `https://dns.${SECRET_DOMAIN}`
2. **TSIG key creation** (Settings → TSIG, HMAC-SHA256)
3. **Dynamic Updates enable** for `${SECRET_DOMAIN}` zone
4. **Security Policy configuration** (allow external-dns key)

### Zone Configuration via API
```bash
# Create primary zone
POST /api/zones/create?zone=${SECRET_DOMAIN}&type=Primary

# Add wildcard fallback
POST /api/zones/records/add?zone=${SECRET_DOMAIN}&type=A&name=*&rdata=192.168.1.58

# Conditional forwarder for local devices
POST /api/zones/create?zone=lan.${SECRET_DOMAIN}&type=Forwarder&forwarder=192.168.1.1
```

## Key Architectural Principles

### External-DNS Configuration
- **Target annotations**: Only on Gateways, never on HTTPRoutes
- **Source configuration**: Use `gateway-httproute` exclusively
- **Inheritance pattern**: HTTPRoutes automatically inherit Gateway targets
- **CNAME enforcement**: Prevents A record fallbacks to LoadBalancer IPs

### App-Template Priority
- **Route field first**: Use app-template `route` field over standalone HTTPRoute
- **Standalone criteria**: Only for external charts or operator-managed resources
- **Configuration co-location**: Keep routing config with application config

### Component-Based Architecture
- **Provider abstraction**: Use `app.kubernetes.io/component` for service selection
- **Zero-downtime migrations**: Enable seamless provider switching
- **Infrastructure separation**: Decouple services from applications

### Network Configuration
- **Gateway IP Assignment**: Use externalIPs approach for Envoy Gateway services (192.168.1.72 internal, 192.168.1.73 external) rather than LoadBalancer + IPAM for predictable, simple IP management
- **External-DNS Architecture**: Configure target annotations on Gateways only, never on HTTPRoutes. Use gateway-httproute source exclusively for CNAME-only records via inheritance

## Configuration Responsibilities

### Technitium DNS Server
- DNS zone management (`${SECRET_DOMAIN}`)
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
- Local device hostname resolution (`*.lan.${SECRET_DOMAIN}`)
- DHCP DNS server assignment (point to `.71`)
- External-DNS unifi-webhook integration (existing)

## Benefits of This Architecture

1. **Migration-Friendly**: Gradual service migration with automatic DNS updates
2. **Zero-Downtime Capable**: Infrastructure changes without service interruption
3. **GitOps Compatible**: All configuration managed via Flux automation
4. **Provider Agnostic**: Easy switching between DNS server implementations
5. **Tunnel Compatible**: Proper CNAME chains for Cloudflare tunnel architecture
6. **Clean Separation**: Pod DNS completely separate from home network DNS
7. **Intelligent Fallback**: Native wildcard → specific record override behavior
8. **High Availability**: Multi-replica deployment with LoadBalancer VIP
9. **Future-Proof**: API-based automation and GitOps integration

## Final Architecture Summary

### HTTPRoute Determines Gateway
Services specify `parentRefs: external` (→ .73) or `parentRefs: internal` (→ .72)

### DNS Returns Same IP
Both internal and external clients get the same resolved IP

### No Short-Circuiting
Internal devices connect directly to the designated gateway IP

### Gateway Selection
Determined by HTTPRoute configuration, not DNS resolution path

### Updated Traffic Flows

**Internal Client to External Service** (e.g., home.${SECRET_DOMAIN}):
```
MacBook → Technitium (.71) → Returns .73 → Direct connection to .73 → K8s external gateway
```

**External Client to External Service**:
```
Android → Cloudflare DNS → Returns Cloudflare IPs → Tunnel → .73 → K8s external gateway
```

**Both reach the same .73 gateway** - difference is routing path, not destination IP.

This architecture provides intelligent conditional forwarding with fallback behavior while maintaining proven external-dns automation patterns and enabling seamless service migrations.
