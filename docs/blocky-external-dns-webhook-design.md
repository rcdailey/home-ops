# Blocky External-DNS Webhook Provider - Technical Design

## Overview

This document outlines the technical requirements and design considerations for creating a webhook provider that enables external-dns integration with Blocky DNS server for automated internal DNS record management.

## Problem Statement

**Current State:**
- Blocky serves as internal DNS server (192.168.1.71) for ad-blocking and local resolution
- External-dns manages Cloudflare records for external access via tunnel
- Internal network devices cannot automatically resolve Kubernetes service hostnames

**Desired State:**
- Internal devices resolve `service.${SECRET_DOMAIN}` → `192.168.1.73` (internal gateway)
- Automatic DNS record creation when Kubernetes services are deployed
- Preserve existing Blocky ad-blocking functionality

## Requirements

### Functional Requirements

1. **External-DNS Webhook API Compliance**
   - Implement standard external-dns webhook provider interface
   - Support HTTP endpoints: `GET /`, `POST /records`, `DELETE /records`, `GET /records`
   - Handle DNS record types: A, AAAA, CNAME minimally

2. **Blocky Integration**
   - Read/modify Blocky configuration files
   - Trigger Blocky configuration reload after changes
   - Preserve existing manual DNS entries and configuration structure

3. **Record Management**
   - Create DNS records from Kubernetes HTTPRoute/Service annotations
   - Update existing records when target IPs change
   - Remove records when Kubernetes resources are deleted
   - Handle record conflicts and ownership tracking

4. **State Management**
   - Track webhook-managed vs manually configured entries
   - Maintain consistency between external-dns state and Blocky config
   - Implement proper cleanup for orphaned records

### Non-Functional Requirements

1. **Reliability**
   - Handle concurrent configuration updates safely
   - Implement retry logic for failed operations
   - Graceful error handling and recovery

2. **Performance**
   - Minimize DNS service disruption during reloads
   - Efficient configuration parsing/serialization
   - Low memory and CPU footprint

3. **Security**
   - Validate input from external-dns requests
   - Secure file system access for configuration management
   - Optional authentication for webhook endpoints

4. **Observability**
   - Comprehensive logging for debugging
   - Health check endpoints
   - Metrics for monitoring record operations

## Architecture Overview

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   external-dns  │───▶│  blocky-webhook  │───▶│     blocky      │
├─────────────────┤    ├──────────────────┤    ├─────────────────┤
│ - Watches K8s   │    │ - HTTP API       │    │ - DNS resolution│
│ - HTTPRoute     │    │ - Config mgmt    │    │ - Ad blocking   │
│ - Services      │    │ - State tracking │    │ - Custom DNS    │
│ - Annotations   │    │ - Reload trigger │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## Technical Components

### 1. Webhook HTTP Server

**Endpoints:**
- `GET /` - Health check and provider information
- `GET /records` - List current DNS records managed by webhook
- `POST /records` - Create or update DNS records
- `DELETE /records` - Remove DNS records

**Request/Response Format:**
```json
// POST/DELETE /records
{
  "dnsName": "grafana.${SECRET_DOMAIN}",
  "targets": ["192.168.1.73"],
  "recordType": "A",
  "recordTTL": 300
}
```

### 2. Blocky Configuration Management

**Configuration Structure:**
```yaml
# Blocky config.yaml
customDNS:
  mapping:
    # Manual entries (preserved)
    router.lan: 192.168.1.1
    printer.lan: 192.168.1.100

    # Webhook-managed entries (dynamic)
    grafana.${SECRET_DOMAIN}: 192.168.1.73
    home.${SECRET_DOMAIN}: 192.168.1.73
```

**Configuration Operations:**
- Parse existing YAML configuration
- Identify webhook-managed vs manual entries
- Update mapping section with new records
- Serialize back to valid YAML format
- Preserve comments and formatting where possible

### 3. Blocky Reload Integration

**Reload Mechanisms (Research Required):**
- Configuration file monitoring and reload
- HTTP API endpoints for reload (if available)
- Process signal handling (SIGHUP)
- Pod restart as fallback option

### 4. State Management

**Record Ownership Tracking:**
- Maintain mapping of DNS names to management source
- Implement conflict resolution for overlapping entries
- Support for record ownership metadata

**Persistence:**
- In-memory state for active session
- Configuration file as source of truth
- Recovery from webhook restarts

## Deployment Architecture

### Container Deployment

**Sidecar Pattern (Recommended):**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: blocky-with-webhook
spec:
  template:
    spec:
      containers:
      - name: blocky
        image: spx01/blocky:latest
        volumeMounts:
        - name: config
          mountPath: /app/config.yaml
          subPath: config.yaml
      - name: blocky-webhook
        image: external-dns-blocky-webhook:latest
        ports:
        - containerPort: 8888
          name: webhook
        volumeMounts:
        - name: config
          mountPath: /app/config.yaml
          subPath: config.yaml
        env:
        - name: BLOCKY_CONFIG_PATH
          value: /app/config.yaml
        - name: WEBHOOK_PORT
          value: "8888"
      volumes:
      - name: config
        configMap:
          name: blocky-config
```

**External-DNS Configuration:**
```yaml
# external-dns HelmRelease
provider: webhook
extraArgs:
  webhook-provider-url: http://blocky-webhook:8888
  domain-filter: ${SECRET_DOMAIN}
  txt-owner-id: blocky-internal
  source: gateway-httproute
```

## Open Research Questions

### Configuration Reload Mechanisms
- **Question:** What reload APIs or patterns does Blocky support?
- **Investigation Needed:**
  - Review Blocky source code for reload functionality
  - Test configuration file monitoring behavior
  - Determine most reliable reload trigger method
- **Alternatives:** HTTP API, file watching, signal handling, container restart

### Configuration File Strategy
- **Question:** Can webhook-managed records use separate YAML files?
- **Investigation Needed:**
  - Blocky's support for configuration includes/imports
  - File watching behavior with multiple config files
  - Separation of concerns between manual and automated entries
- **Benefits:** Cleaner separation, reduced conflict risk, easier debugging

### Deployment Patterns Research
- **Question:** What are established best practices for webhook provider deployment?
- **Investigation Needed:**
  - Review existing webhook providers (AdGuard, Unifi, Hetzner, etc.)
  - Analyze sidecar vs standalone service patterns
  - Security and reliability patterns in the ecosystem
- **Examples to Study:**
  - `external-dns-provider-adguard` architecture
  - `external-dns-unifi-webhook` deployment model
  - Official external-dns webhook documentation

## Implementation Phases

### Phase 1: Proof of Concept
- Minimal HTTP server with webhook API endpoints
- Basic Blocky configuration file parsing
- Simple record create/delete operations
- Manual testing with external-dns

### Phase 2: Core Functionality
- Complete webhook API implementation
- Robust YAML configuration management
- Blocky reload integration
- State management and conflict resolution

### Phase 3: Production Readiness
- Comprehensive error handling and recovery
- Logging, metrics, and observability
- Security hardening
- Documentation and examples

### Phase 4: Community Contribution
- Open source repository creation
- CI/CD pipeline and automated testing
- Docker image publishing
- External-DNS ecosystem integration

## Success Criteria

1. **Functional Success:**
   - HTTPRoute annotations create corresponding DNS records in Blocky
   - Internal devices resolve Kubernetes service hostnames correctly
   - External-DNS operates without errors or conflicts

2. **Operational Success:**
   - Webhook survives Blocky restarts and configuration changes
   - No DNS service interruption during record updates
   - Clear troubleshooting and debugging capabilities

3. **Community Success:**
   - Documentation sufficient for others to deploy and use
   - Integration with external-dns webhook provider ecosystem
   - Positive community feedback and adoption

## Repository Structure

```
external-dns-blocky-webhook/
├── cmd/
│   └── webhook/
│       └── main.go
├── internal/
│   ├── blocky/
│   ├── webhook/
│   └── config/
├── pkg/
│   └── api/
├── deployments/
│   ├── kubernetes/
│   └── docker-compose/
├── docs/
├── examples/
├── Dockerfile
├── go.mod
└── README.md
```

## Conclusion

This webhook provider would bridge external-dns and Blocky to enable automated internal DNS record management while preserving existing ad-blocking functionality. The implementation represents a meaningful contribution to the external-dns ecosystem and addresses a gap in Blocky's dynamic DNS capabilities.

The project requires careful attention to configuration management, reload mechanisms, and deployment patterns to ensure reliability and adoption in production environments.
