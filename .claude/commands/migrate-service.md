---
description: Systematic Docker Compose to Kubernetes migration with comprehensive discovery and analysis
argument-hint: <service-name> - Name of the service to migrate from docker-compose
---

# Docker Compose to Kubernetes Migration Protocol

**CRITICAL: This command REQUIRES Plan Mode. Exit immediately if not in Plan Mode.**

**TARGET SERVICE**: $ARGUMENTS

*If no service name provided, request user specify the service to migrate.*

## Phase 1: Pre-flight Validation

**MANDATORY SYSTEM CHECKS:**

1. **Plan Mode Verification**
   - Confirm Plan Mode is active
   - Exit with error if not in Plan Mode

2. **Mount Accessibility Check**
   - Detect OS and check appropriate mount path
   - WSL2/Linux: `/mnt/fast/docker`
   - macOS: `/Volumes/docker`
   - If mount not accessible, STOP and require user to fix mount

3. **Service Pre-existence Check**
   - Search existing cluster deployments for the target service
   - Search for any references to the service in kubernetes manifests
   - If service already exists, document current state and ask user for migration intent

## Phase 2: Discovery & Configuration Analysis

**DOCKER COMPOSE DISCOVERY:**

1. **Locate Service Configuration**
   - Search for service directory in docker mount
   - Search for docker-compose files in service directory
   - If not found, request user provide exact path

2. **Configuration Extraction**
   - Read primary docker-compose file from discovered service path
   - Read environment files (.env) if they exist
   - Read any override files (docker-compose.override.yml) if they exist
   - Document custom config files (*.conf,*.cfg, *.json,*.yaml)

3. **Volume Analysis**
   - List all volumes and bind mounts in the service directory
   - Identify data persistence requirements
   - Map to K8s storage strategy (NFS, Rook Ceph, local)

4. **Network & Port Analysis**
   - Extract exposed ports and networking requirements
   - Identify database dependencies
   - Document external service integrations

## Phase 3: Reference Implementation Research

**ENHANCED RESEARCH STRATEGY:**

1. **Context7 Library Documentation (MANDATORY FIRST STEP)**
   - **REQUIRED**: `resolve-library-id` for "bjw-s app-template" or "app-template"
   - **REQUIRED**: `get-library-docs` with Context7-compatible library ID
   - Document current app-template patterns, values structure, and best practices
   - **CRITICAL**: This provides authoritative, up-to-date documentation before any implementation decisions
   - Extract controller patterns, persistence options, and networking configurations from official docs

2. **Local Repository Analysis (PRIORITY)**
   - Search existing app-template implementations: `rg -l "app-template"
     kubernetes/apps/*/*/helmrelease.yaml`
   - Analyze controller patterns in similar applications
   - Extract service architecture decisions from existing deployments
   - Document storage, networking, and security patterns used
   - **Anti-pattern Detection**: Identify multi-service containers that should be separate
     HelmReleases

3. **Service Architecture Decision Rules**

   ```yaml
   Separate HelmReleases (Different Pods) IF:
     - Independent database (MariaDB, PostgreSQL, Redis as primary store)
     - Different lifecycle management needs
     - Different resource/security requirements
     - Can function independently

   Same HelmRelease, Separate Controllers (Different Pods) IF:
     - Tightly coupled services (web + worker + cache)
     - Shared configuration and secrets
     - Similar resource requirements
     - Part of same application stack

   Same Controller, Multiple Containers (Same Pod) IF:
     - Sidecar pattern (VPN + app, backup + app)
     - Shared network namespace required
     - Init container dependencies
     - Shared storage access patterns
   ```

4. **OctoCode External Research (Systematic Analysis)**
   - **Repository Structure**: `githubViewRepoStructure` for onedr0p/home-ops kubernetes/apps structure
   - **Pattern Discovery**: Bulk `githubSearchCode` queries:
     ```
     Query Set A: ["$ARGUMENTS", "app-template", "bjw-s"]
     Query Set B: ["controllers", "persistence", "route"]
     Query Set C: Service-specific terms from docker-compose analysis
     ```
   - **Implementation Analysis**: `githubGetFileContent` for specific helmrelease.yaml examples
   - **Benefit**: Comprehensive pattern analysis with parallel bulk operations

5. **App-Scout Analysis (Chart Discovery)**
   - **REQUIRED**: Run app-scout discovery for the target service
   - Analyze dedicated charts vs app-template patterns
   - Compare with context7 + octocode findings
   - **Purpose**: Chart availability assessment, not implementation patterns (use octocode for patterns)

6. **Documentation Validation Cross-Check**
   - Validate octocode findings against context7 documentation
   - Ensure implementation patterns align with current app-template best practices
   - Document any discrepancies between external patterns and official documentation

## Phase 4: Migration Strategy Decision Tree

**DEPLOYMENT PATTERN SELECTION:**

1. **Chart vs App-Template Decision**

   ```yaml
   Use Dedicated Helm Chart IF:
     - Official chart exists and is actively maintained
     - Complex configuration requirements
     - Multiple interdependent services
     - Database clustering needs

   Use App-Template IF:
     - Simple single-container service
     - Custom configuration requirements
     - Need fine-grained control
     - Homelab-specific customizations
   ```

2. **Storage Strategy Selection**

   ```yaml
   Use NFS IF:
     - Large media files (>10GB)
     - Shared across multiple pods
     - Existing data on Nezuko NFS

   Use Rook Ceph IF:
     - Database storage
     - High-performance requirements
     - Replicated storage needs

   Use Local Storage IF:
     - Temporary/cache data
     - Single-node requirements
   ```

3. **Network Exposure Decision**

   ```yaml
   Use HTTPRoute IF:
     - Web interface required
     - External access needed
     - HTTPS/TLS termination

   Use ClusterIP Service IF:
     - Internal-only access
     - API endpoints for other services
     - Database connections

   Use LoadBalancer IF:
     - Non-HTTP protocols (rare in homelab)
     - User explicitly requests it
   ```

## Phase 5: Kubernetes Resource Planning

**ENHANCED RESOURCE MAPPING:**

1. **Service Architecture Decision**
   - Apply Phase 3 decision rules to each docker-compose service
   - Cross-reference with context7 app-template documentation patterns
   - Validate against octocode research findings from onedr0p/home-ops
   - Create dependency graph showing which services need separation
   - Document rationale for each architectural decision with reference citations

2. **App-Template Configuration Strategy**
   - **OCIRepository Pattern**: Use `oci://ghcr.io/bjw-s-labs/helm/app-template` (confirmed from octocode research)
   - **Version Selection**: Document version found in research (e.g., `tag: 4.3.0` from onedr0p patterns)
   - **Controller Structure**: Plan based on context7 documentation + octocode examples
   - **Storage Strategy**: Apply RWO vs RWX patterns from research analysis

3. **Namespace Selection**
   - Analyze existing namespaces: `ls -d kubernetes/apps/*/`
   - Follow semantic grouping (dns-private, network, default, etc.)
   - Use existing namespace or justify new one

4. **Directory Structure Planning**

   **Single Service Pattern (App-Template):**

   ```txt
   kubernetes/apps/<namespace>/$ARGUMENTS/
   ├── ks.yaml               # Kustomization with targetNamespace
   ├── kustomization.yaml     # Resource list
   └── app/
       ├── helmrelease.yaml   # App-template deployment
       ├── ocirepository.yaml # App-template chart reference
       ├── secret.sops.yaml   # Encrypted secrets (if needed)
       ├── httproute.yaml     # External access (if needed)
       └── pvc.yaml          # Persistent volumes (if needed)
   ```

   **Multi-Service Pattern (Databases Separated):**

   ```txt
   kubernetes/apps/<namespace>/$ARGUMENTS/
   ├── ks.yaml               # Kustomization with targetNamespace
   ├── kustomization.yaml     # Resource list
   ├── app/
   │   ├── helmrelease.yaml   # Main app (app-template)
   │   ├── ocirepository.yaml # App-template chart reference
   │   ├── secret.sops.yaml   # App-specific secrets
   │   ├── httproute.yaml     # External access
   │   └── pvc.yaml          # App persistent volumes
   └── database/
       ├── helmrelease.yaml   # Database (dedicated chart)
       ├── secret.sops.yaml   # Database secrets
       └── pvc.yaml          # Database persistent volumes
   ```

5. **Volume Mounting Strategy (Enhanced)**
   - **globalMounts**: Use for RWX volumes, ConfigMaps, shared data
   - **advancedMounts**: REQUIRED for RWO volumes, specific controller targeting
   - **Strategy Requirement**: `strategy: Recreate` for any RWO persistent volumes
   - **Reference**: Based on onedr0p patterns and app-template documentation

6. **Secret Planning**
   - Extract environment variables from docker-compose
   - Group secrets by service boundaries (app vs database)
   - Plan secret integration method (envFrom priority, then valueFrom)
   - Use dedicated database operators (MariaDB, CNPG) for database credentials

## Phase 6: Migration Implementation Plan

**COMPREHENSIVE IMPLEMENTATION CHECKLIST:**

1. **Repository Structure**
   - Create directory: `kubernetes/apps/<namespace>/$ARGUMENTS/`
   - Generate kustomization.yaml with resource list
   - Add to parent namespace kustomization

2. **Enhanced Core Deployment (Context7 + OctoCode Patterns)**
   - **Context7 Validation**: Verify implementation against official app-template documentation
   - **OctoCode Patterns**: Apply patterns discovered from onedr0p/home-ops analysis
   - **Local Integration**: Adapt patterns to existing repository conventions
   - Create ocirepository.yaml with:
     - `url: oci://ghcr.io/bjw-s-labs/helm/app-template`
     - Version from research findings (e.g., `tag: 4.3.0`)
   - Create helmrelease.yaml with:
     - YAML language server schema (Flux schemas)
     - OCIRepository chartRef referencing app-template
     - Controllers structure from context7 documentation
     - Service definitions matching controller names
     - Resource requests/limits from docker-compose analysis
     - Security context patterns: runAsNonRoot, capabilities drop, readOnlyRootFilesystem
     - Health probes (HTTP preferred, custom probes for complex apps)
     - Reloader annotation: `reloader.stakater.com/auto: "true"`
     - Volume mounting strategy: advancedMounts for RWO, globalMounts for RWX

3. **Database Integration (Critical Decision Point)**
   - **If database required**: Create separate HelmRelease using dedicated operator
   - **MariaDB**: Use mariadb-operator following kubernetes/apps/kube-system/mariadb-operator/
   - **PostgreSQL**: Use cloudnative-pg following kubernetes/apps/kube-system/cloudnative-pg/
   - **Redis**: Include as controller only if used as cache, not primary store

4. **Storage Configuration**
   - Create PVC manifests for persistent data
   - Configure subPath mounting for existing data
   - Plan data migration from docker volumes

5. **Secret Management**
   - Create secret.sops.yaml structure
   - Use `sops --set` commands for value insertion
   - Configure secret integration in helmrelease

6. **Network Configuration**
   - Create HTTPRoute for external access (if needed)
   - Configure service endpoints
   - Set up external-dns annotations

7. **Validation Strategy**
   - Pre-commit validation: `pre-commit run --files <changed-files>`
   - Flux validation: `./scripts/flux-local-test.sh`
   - Kustomize build test: `kustomize build kubernetes/apps/<namespace>/$ARGUMENTS`

## Phase 7: Migration Execution Workflow

**STEP-BY-STEP EXECUTION:**

1. **Pre-Migration Backup**
   - Document current docker-compose state
   - Backup volume data if critical
   - Note current service URLs and access methods

2. **Gradual Migration Approach**
   - Deploy to K8s alongside docker-compose
   - Validate functionality matches
   - Migrate DNS/routing when validated
   - Remove docker-compose deployment

3. **Post-Migration Validation**
   - Verify all functionality working
   - Check data persistence across pod restarts
   - Validate external access and authentication
   - Monitor logs for errors

4. **GitOps Integration**
   - Commit changes to repository
   - Monitor Flux reconciliation
   - Verify automatic deployment
   - Use `task reconcile` for immediate sync

## Enhanced Tool Integration Patterns

**CONTEXT7 INTEGRATION:**
```
1. resolve-library-id: "bjw-s app-template" or "app-template"
2. get-library-docs: Use resolved Context7-compatible library ID
3. Extract: Current patterns, controller structure, persistence options
4. Validate: All implementation decisions against official documentation
```

**OCTOCODE BULK RESEARCH STRATEGY:**
```
Sequential Query Sets for onedr0p/home-ops:
1. Repository Structure: githubViewRepoStructure kubernetes/apps
2. Pattern Discovery: githubSearchCode parallel queries:
   - Service-specific: [$ARGUMENTS, related-terms]
   - App-template: ["app-template", "bjw-s", "controllers"]
   - Architecture: ["persistence", "route", "security"]
3. Implementation Analysis: githubGetFileContent for specific examples
4. Cross-reference: Validate findings against context7 documentation
```

**APP-SCOUT FOCUSED USAGE:**
```
Purpose: Chart availability assessment only
Workflow:
1. ./scripts/app-scout.sh discover $ARGUMENTS
2. Identify dedicated charts vs app-template decision
3. Use octocode for implementation patterns (not app-scout inspect)
```

## Critical Operational Rules

**MANDATORY COMPLIANCE:**

- **Context7 First**: ALWAYS start with context7 library documentation lookup - no implementation without official docs
- **Service Separation**: NEVER put databases as containers in app-template controllers
- **Research Priority**: Context7 → Local Repository → OctoCode → App-Scout workflow
- **Architecture Validation**: Apply Phase 3 decision rules to prevent multi-container anti-patterns
- **GitOps Only**: Never modify cluster directly, only repository YAML
- **SOPS Security**: All secrets encrypted before commit
- **Schema Validation**: Include yaml-language-server directives
- **Reference Format**: Use `file.yaml:123` when citing code (include onedr0p references for external patterns)
- **Validation**: Always run flux-local-test.sh and pre-commit before handoff
- **No Assumptions**: Validate all patterns against context7 documentation and octocode findings
- **Tool Integration**: Use octocode bulk operations for external research efficiency
- **Collaborative**: Present complete architectural analysis with research citations and ask for user confirmation

## Final Deliverables

**MIGRATION PLAN OUTPUT:**

1. **Service Analysis Report**
   - Current docker-compose configuration summary
   - Resource requirements and dependencies
   - Storage and networking needs

2. **Implementation Strategy**
   - Deployment pattern decision (chart vs app-template)
   - Storage strategy selection
   - Security and networking configuration

3. **File Structure Visualization**

   ```txt
   kubernetes/apps/<namespace>/$ARGUMENTS/
   [Detailed ASCII tree of all files to be created]
   ```

4. **Migration Checklist**
   - Pre-migration tasks
   - Implementation steps
   - Validation procedures
   - Rollback plan

5. **Risk Assessment**
   - Potential migration challenges
   - Data loss prevention measures
   - Service availability considerations

**REMEMBER: This is PLANNING ONLY. Present complete plan and wait for user approval before any
implementation.**
