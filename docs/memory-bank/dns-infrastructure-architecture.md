# DNS Infrastructure Architecture

## Current Implementation Status (2025-08-02)

### ✅ COMPLETED: Gateway & External-DNS Architecture

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

**Architecture Benefits**:
- ✅ CNAME-only DNS records (no A records from Gateway IPs)
- ✅ Cloudflare tunnel compatibility restored
- ✅ Automatic inheritance (impossible to deploy HTTPRoute without target)
- ✅ Zero-downtime service migrations

### ✅ COMPLETED: App-Template Route Field Migration

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
- ✅ Eliminated 3 standalone HTTPRoute files (50% reduction)
- ✅ Co-located routing config with application config
- ✅ Consistent app-template patterns across services

### ✅ COMPLETED: DNS Gateway Infrastructure Separation

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
- ✅ Zero-downtime DNS provider switching capability
- ✅ Infrastructure/application separation achieved
- ✅ Future Blocky/other DNS provider support ready

## Current Infrastructure Overview

### Network Architecture
- **Network**: `192.168.1.0/24`
- **Gateway**: `192.168.1.1` (UniFi Dream Machine Pro)
- **Domain**: `$(SECRET_DOMAIN}` (managed by Cloudflare)
- **DNS Gateway**: `192.168.1.71` (Technitium DNS via LoadBalancer)
- **Internal Gateway**: `192.168.1.72` (Envoy Gateway - LAN services)
- **External Gateway**: `192.168.1.73` (Envoy Gateway - WAN/tunnel services)

### Current DNS Services
- **Technitium DNS** (`192.168.1.71`): Primary DNS with provider-agnostic infrastructure
- **CoreDNS** (internal): Cluster DNS resolution (`*.cluster.local`)
- **Cloudflare External-DNS**: Public internet DNS record management
- **Technitium External-DNS**: Internal service DNS automation (planned)

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
- **A) `device.lan.$(SECRET_DOMAIN}`**: Conditional forwarder → `192.168.1.1` (UDMP)
- **B) `foo.$(SECRET_DOMAIN}`** (exists in K8s): Zone lookup → Gateway IP via External-DNS
- **C) `unknown.$(SECRET_DOMAIN}`** (not in K8s): Wildcard A record → `192.168.1.58` (fallback)
- **D) `google.com`**: Upstream forwarder → `1.1.1.1, 8.8.8.8`

## 📋 PENDING: Dual External-DNS Architecture

### Current State
- **Cloudflare External-DNS**: ✅ Managing external HTTPRoutes → Cloudflare tunnel
- **Technitium External-DNS**: 🔄 Configured but needs deployment completion

### Planned Implementation

**Cloudflare External-DNS** (unchanged):
```yaml
provider: cloudflare
sources: ["crd", "gateway-httproute"]
# Creates Cloudflare records for external HTTPRoutes only
```

**Technitium External-DNS** (pending):
```yaml
provider: rfc2136
sources: ["crd", "gateway-httproute"]
rfc2136:
  host: "technitium-dns-app.network.svc.cluster.local"
  port: 53
  zone: "$(SECRET_DOMAIN}"
  insecure: true
  # Creates internal DNS records for all HTTPRoutes
```

### DNS Record Distribution (Target State)
- **External HTTPRoutes** (`parentRefs: external`) → Cloudflare DNS → Tunnel endpoint
- **Internal HTTPRoutes** (`parentRefs: internal`) → Technitium DNS → Internal gateway IP
- **Both internal and external HTTPRoutes** → Technitium DNS (local resolution)

### Target Inheritance Behavior
- **External services**: Inherit `external.${SECRET_DOMAIN}` → CNAME to tunnel
- **Internal services**: Inherit `internal.${SECRET_DOMAIN}` → CNAME to internal gateway

### Required Manual Configuration
1. **Technitium Web UI Setup**:
   - Admin password change via `https://dns.$(SECRET_DOMAIN}`
   - TSIG key creation (Settings → TSIG, HMAC-SHA256)
   - Dynamic Updates enable for `$(SECRET_DOMAIN}` zone
   - Security Policy configuration

2. **Zone Configuration via API**:
   ```bash
   # Create primary zone
   POST /api/zones/create?zone=$(SECRET_DOMAIN}&type=Primary

   # Add wildcard fallback
   POST /api/zones/records/add?zone=$(SECRET_DOMAIN}&type=A&name=*&rdata=192.168.1.58

   # Conditional forwarder for local devices
   POST /api/zones/create?zone=lan.$(SECRET_DOMAIN}&type=Forwarder&forwarder=192.168.1.1
   ```

## Migration Planning

### Service Migration Workflow
1. **Deploy K8s service**: Create HTTPRoute with correct parentRefs
2. **Automatic DNS**: External-DNS detects HTTPRoute and creates records
3. **Target inheritance**: HTTPRoute inherits correct target from Gateway
4. **DNS resolution**: Specific record overrides wildcard fallback
5. **Traffic flows**: Home devices connect to appropriate gateway

### Future DNS Provider Migration (Technitium → Blocky)
1. **Deploy Blocky** with `app.kubernetes.io/component: dns-server` label
2. **Zero-downtime cutover**: dns-gateway automatically routes to both providers
3. **Remove Technitium label**: DNS traffic routes only to Blocky
4. **Clean removal**: Delete Technitium without DNS service interruption

## Implementation Priorities

### High Priority 🔴
1. **Complete Technitium External-DNS deployment** (Kustomization issue resolution)
2. **Manual Technitium configuration** (TSIG key, zones, security)
3. **RFC2136 integration testing** (External-DNS → Technitium automation)

### Medium Priority 🟡
1. **Wildcard fallback configuration** (`*.$(SECRET_DOMAIN} → 192.168.1.58`)
2. **UDMP DNS server update** (point home devices to `192.168.1.71`)
3. **k8s-gateway decommission** (IP address migration)

### Low Priority 🟢
1. **Ad-blocking integration** (separate service vs integrated solution)
2. **DNS provider evaluation** (Blocky alternative assessment)
3. **High availability enhancement** (when clustering becomes available)

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

## Benefits of Current Architecture

1. **Migration-Friendly**: Gradual service migration with automatic DNS updates
2. **Zero-Downtime Capable**: Infrastructure changes without service interruption
3. **GitOps Compatible**: All configuration managed via Flux automation
4. **Provider Agnostic**: Easy switching between DNS server implementations
5. **Tunnel Compatible**: Proper CNAME chains for Cloudflare tunnel architecture
6. **Clean Separation**: Pod DNS completely separate from home network DNS

This architecture provides intelligent conditional forwarding with fallback behavior while maintaining proven external-dns automation patterns and enabling seamless service migrations.
