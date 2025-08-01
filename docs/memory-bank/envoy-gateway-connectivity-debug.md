# Envoy Gateway Connectivity Debug Session

## Issue Summary

**Primary Problem**: `https://dns-test.$(SECRET_DOMAIN}` returns connection timeout (originally reported as HTTP 500)

**Root Cause**: Internal gateway IP `192.168.1.72` is not reachable at network level despite correct DNS resolution

**Date**: 2025-08-02
**Context**: Investigation of connectivity issues after Envoy Gateway configuration changes

## Architecture Understanding (CONFIRMED ✅)

### Gateway Design
- **Internal Gateway**: `192.168.1.72` - LAN-only services, HTTPRoutes with `parentRefs: internal`
- **External Gateway**: `192.168.1.73` - Internet-accessible services via Cloudflare tunnel, HTTPRoutes with `parentRefs: external`

### DNS Architecture
- **External services**: Cloudflare external-dns creates public DNS records → Cloudflare tunnel → `.73`
- **Internal services**: Planned dual external-dns (Cloudflare + Technitium RFC2136) → `.72` for local access
- **Current state**: Using AdGuard Home DNS rewrite for `dns-test.$(SECRET_DOMAIN} → 192.168.1.72` during transition

### Service Flow (Intended)
1. User visits `https://foo.$(SECRET_DOMAIN}` from LAN
2. DNS resolves to `192.168.1.72` (via local DNS)
3. Traffic hits internal gateway at `.72`
4. Envoy Gateway routes to appropriate pod via HTTPRoute

## Timeline of Changes

### Original Working State (July 13, 2025)
- Envoy Gateway using `externalIPs` approach
- Gateways specified IPs directly in Gateway resources
- No LoadBalancer services from Cilium IPAM

### Breaking Change (August 1, 2025 - tip commit)
```yaml
# Added to Envoy Gateway configuration
provider:
  kubernetes:
    envoyService:
      type: LoadBalancer
      externalTrafficPolicy: Cluster
```

### Impact of Change
- Cilium began assigning additional LoadBalancer IPs from pool
- Internal gateway: Got `192.168.1.2` + intended `192.168.1.72`
- External gateway: Got `192.168.1.1` + intended `192.168.1.73`
- Neither IP became reachable

### Revert Attempt (August 2, 2025)
- Removed LoadBalancer configuration from Envoy Gateway
- Deleted and recreated gateway services
- Services still show LoadBalancer + externalIPs behavior
- Connectivity issue persists

## Current System State

### DNS Resolution ✅
```bash
$ nslookup dns-test.$(SECRET_DOMAIN}
Name: dns-test.$(SECRET_DOMAIN}
Address: 192.168.1.72  # Correct via AGH rewrite
```

### Gateway Resources ✅
```bash
$ kubectl get gateway internal external -n network
NAME       ADDRESS        PROGRAMMED
internal   192.168.1.72   True
external   192.168.1.73   True
```

### Service Configuration ❌
```bash
$ kubectl get service envoy-network-internal-f0b82637 -n network
TYPE:                     LoadBalancer
External IPs:             192.168.1.72
LoadBalancer Ingress:     192.168.1.2 (VIP)
```

### Network Connectivity ❌
```bash
$ ping 192.168.1.72
Request timeout for icmp_seq 0
# IP is not reachable
```

### Working Systems ✅
- External gateway via Cloudflare: `https://home.$(SECRET_DOMAIN}` works
- Internal cluster routing: HTTPRoute shows as "Accepted"
- Envoy proxy logs show successful routing to backend pods

## Investigated Areas

### Cilium Configuration ❌
**LoadBalancer IP Pool**: Too broad - `192.168.1.0/24` instead of `192.168.1.70/28`
```yaml
spec:
  blocks:
  - cidr: 192.168.1.0/24  # Should be 192.168.1.70/28
```

**L2 Announcement Policy**: Appears correct
```yaml
spec:
  loadBalancerIPs: true
  nodeSelector:
    matchLabels:
      kubernetes.io/os: linux
```

### Pod Distribution
- **Internal gateway pod**: Running on `marin` (192.168.1.59)
- **External gateway pod**: Running on `nami` (192.168.1.50)
- **externalTrafficPolicy**: `Local` (requires traffic to hit correct node)

### External-DNS Status
- **Cloudflare external-dns**: Running, managing external HTTPRoutes
- **Technitium external-dns**: Configured but NOT deployed (kustomization not found)
- **Internal services**: Currently relying on manual DNS (AGH rewrite)

## Issues Status

### RESOLVED ✅
1. **DNS Resolution**: Working via AdGuard Home rewrite
2. **Architecture Understanding**: Clear on internal vs external gateway purposes
3. **Configuration Changes**: Identified breaking change and reverted config
4. **External Services**: Confirmed working (home.$(SECRET_DOMAIN})
5. **Git History Analysis**: Found exact commit that broke things
6. **Memory Bank Documentation**: Architecture well documented

### ACTIVE INVESTIGATION ❌
1. **Core Issue: 192.168.1.72 connectivity** - IP not reachable (CURRENT FOCUS)

### BLOCKED/PENDING ❌
2. **Cilium LoadBalancer IP pool** - Pool too broad, causing wrong IP assignments
3. **Service creation behavior** - Envoy still creates LoadBalancer despite config revert
4. **Technitium external-dns deployment** - Configured but not running
5. **Cilium L2 announcement** - Suspect this is why .72 isn't reachable

### DEFERRED (for later) 📋
- **Load balancer vs externalIPs approach** - Decided on externalIPs, may need enforcement
- **IP pool reconfiguration** - Needs planning to avoid breaking existing services
- **Full Technitium migration** - Waiting for connectivity resolution

## Next Investigation Focus

**Target**: Why is `192.168.1.72` not reachable at network level?

**Areas to check**:
1. Cilium L2 announcement status for `192.168.1.72`
2. Which node should be announcing this IP
3. Network-level conflicts or misconfigurations
4. Comparison with working external gateway at `192.168.1.73`

**Success criteria**: `ping 192.168.1.72` succeeds from local network

## Test Environment

- **Local DNS**: AdGuard Home at `192.168.1.58` (temporary)
- **Target DNS**: Technitium at `192.168.1.71` (deployed but not configured)
- **Working external service**: `https://home.$(SECRET_DOMAIN}`
- **Broken internal service**: `https://dns-test.$(SECRET_DOMAIN}`

## Key Learnings

1. **LoadBalancer configuration** in Envoy Gateway fundamentally changes behavior
2. **Cilium IPAM** needs proper IP range configuration to prevent conflicts
3. **L2 announcement** is critical for LoadBalancer IP reachability
4. **DNS architecture** is well planned but implementation is in transition state
5. **Manual DNS entries** are effective for testing during migration

## IPAM vs externalIPs Analysis (2025-08-02)

### Architecture Conflict Discovered
**Problem**: Services have both IPAM (LoadBalancer) and externalIPs configured simultaneously
- **IPAM assigns**: 192.168.1.1, 192.168.1.2 (auto-assigned, L2 announced)
- **externalIPs specify**: 192.168.1.72, 192.168.1.73 (manual, not announced)
- **Result**: Only IPAM IPs are reachable, intended IPs (.72, .73) unreachable

### Factual Findings
**IPAM Static IP Support**: ✅ Via `lbipam.cilium.io/ips: "192.168.1.72,192.168.1.73"` annotation
**Cilium Pool Configuration**: Currently `192.168.1.0/24` (entire subnet) - causes IP conflicts
**Default Envoy Gateway Behavior**: Always creates LoadBalancer services when Gateway has addresses

### Recommended Solution
**Use IPAM with static IP annotations** instead of externalIPs:
1. **Keep LoadBalancer services** (remove externalIPs field)
2. **Add IPAM annotations**: `lbipam.cilium.io/ips: "192.168.1.72"`
3. **Fix Cilium IP pool**: Change from `/24` to `192.168.1.70-79` range
4. **Automatic L2 announcement**: Cilium handles network reachability

**Benefits over externalIPs**:
- ✅ Automatic L2 announcement (no manual network setup)
- ✅ Health checks and load balancing features
- ✅ Kubernetes-native management
- ✅ Static IP assignment with `lbipam.cilium.io/ips` annotation

## External-DNS Architecture Fixes (2025-08-02)

### DNS Target Inheritance Implementation
**Issue**: External-DNS created A records from Gateway LoadBalancer IPs instead of CNAMEs to tunnel endpoints
**Root Cause**: HTTPRoutes without target annotations fall back to Gateway LoadBalancer IPs

**Solution Implemented**: Target annotation inheritance pattern
```yaml
# Gateway configuration (target annotation source)
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  annotations:
    external-dns.alpha.kubernetes.io/target: external.${SECRET_DOMAIN}  # external gateway
    external-dns.alpha.kubernetes.io/target: internal.${SECRET_DOMAIN}  # internal gateway

# HTTPRoute configuration (inherits target from Gateway)
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
- ✅ Gateway LoadBalancer IPs ignored by External-DNS

### App-Template Route Field Migration
**Implementation**: Consolidated routing configuration with application config

**Before**: Separate HTTPRoute files
```yaml
# Separate file: app/httproute.yaml
apiVersion: gateway.networking.k8s.io/v1
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

**Migration Results**:
- ✅ Eliminated 3 standalone HTTPRoute files (50% reduction)
- ✅ Co-located routing config with application config
- ✅ Consistent app-template patterns
- ✅ Same inheritance behavior

### DNS Gateway Infrastructure Separation
**Issue**: DNS server application (Technitium) coupled with DNS infrastructure (LoadBalancer service)
**Impact**: DNS provider migration would cause downtime

**Solution**: Separated infrastructure from application
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
    app.kubernetes.io/component: dns-server  # Provider-agnostic selector
  ports:
  - name: dns-tcp
    port: 53
    protocol: TCP
  - name: dns-udp
    port: 53
    protocol: UDP
```

```yaml
# Application: technitium-dns
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
spec:
  values:
    controllers:
      technitium-dns:
        labels:
          app.kubernetes.io/component: dns-server  # Connects to dns-gateway
    service:
      app:
        ports:
          http:
            port: 5380  # Web UI only
          dns-tcp:
            port: 53    # For dns-gateway selector
          dns-udp:
            port: 53
```

**Migration Benefits**:
- ✅ Zero-downtime DNS provider switching
- ✅ Infrastructure/application separation
- ✅ Future Blocky/other DNS provider deployment without IP conflicts
- ✅ Component-based service selection

### Technitium External-DNS Future Configuration
**Planned Implementation**: Dual External-DNS for internal services

**Current State**:
- Cloudflare External-DNS: Manages external HTTPRoutes → Cloudflare tunnel
- Technitium External-DNS: Configured but needs deployment

**Future Architecture**:
```yaml
# technitium-external-dns configuration
sources: ["crd", "gateway-httproute"]
provider: rfc2136
rfc2136:
  host: "technitium-dns-app.network.svc.cluster.local"
  port: 53
  zone: "$(SECRET_DOMAIN}"
  insecure: true
  # Creates internal DNS records for internal HTTPRoutes
```

**DNS Record Distribution**:
- **External HTTPRoutes** (`parentRefs: external`) → Cloudflare DNS → Tunnel
- **Internal HTTPRoutes** (`parentRefs: internal`) → Technitium DNS → Internal gateway IP

**Target Inheritance Behavior**:
- External services: Inherit `external.${SECRET_DOMAIN}` → CNAME to tunnel
- Internal services: Inherit `internal.${SECRET_DOMAIN}` → CNAME to internal gateway

**Benefits of Dual External-DNS**:
- ✅ Automatic DNS management for internal services
- ✅ No manual DNS entries required
- ✅ Consistent HTTPRoute patterns (internal vs external)
- ✅ Clean separation of public vs private DNS zones

### CLAUDE.md Documentation Updates
**Added Guidelines**:

**External-DNS Architecture**:
- Configure target annotations on Gateways only, never on HTTPRoutes
- Use gateway-httproute source exclusively
- Ensures CNAME-only records via inheritance
- Prevents A record fallbacks to LoadBalancer IPs

**App-Template Priority**:
- Always use app-template `route` field over standalone HTTPRoute
- Only use standalone HTTPRoute for external charts or operator-managed resources
- Co-locate routing configuration with application configuration

**Component-Based Service Selection**:
- Use `app.kubernetes.io/component` labels for infrastructure service selection
- Enables provider-agnostic infrastructure (e.g., dns-gateway → any DNS server)
- Supports zero-downtime migrations between providers
