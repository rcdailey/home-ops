---
allowed-tools: Read, Glob, Grep, TodoWrite, Bash(ls:*), Bash(rg:*), Bash(./scripts/app-scout.sh discover:*), Bash(./scripts/flux-local-test.sh:*), Bash(pre-commit run:*), Bash(kustomize build:*), mcp__context7__resolve-library-id, mcp__context7__get-library-docs, mcp__octocode__githubSearchCode, mcp__octocode__githubGetFileContent, mcp__octocode__githubViewRepoStructure
argument-hint: <service-name> - Name of the service to migrate from docker-compose
description: Systematic Docker Compose to Kubernetes migration with comprehensive discovery and analysis
---

# Docker Compose to Kubernetes Migration Protocol

**TARGET SERVICE**: $ARGUMENTS

*If no service name provided, request user specify the service to migrate.*

## Critical Constraints

**MANDATORY REQUIREMENTS:**

- Plan Mode REQUIRED - exit immediately if not in Plan Mode
- NO file modifications until plan approval from user
- NO implementation until ALL research phases complete
- ALL solutions MUST be GitOps-based (repository YAML only)
- Use `rg` (ripgrep) instead of `grep` for all searches
- ALWAYS use Context7 for ANY unknown concepts, tools, or patterns

**DESIGN PHILOSOPHY:**

- Docker Compose is REFERENCE ONLY for extracting requirements (containers, dependencies,
  environment variables, volumes, ports)
- Docker Compose architecture/structure should NOT influence Kubernetes implementation
- Design Kubernetes-first: Follow Context7 app-template docs and repository conventions
- Use modern patterns from research findings, not legacy docker-compose patterns
- Match existing patterns in kubernetes/apps/ directory structure

**MOUNT ACCESSIBILITY CHECK:**

- WSL2/Linux: `/mnt/fast/docker`
- macOS: `/Volumes/docker`
- If mount not accessible, STOP and require user to fix mount

## Pre-Flight Validation

1. **Confirm Plan Mode active** - Exit with error if not in Plan Mode
2. **Check mount accessibility** - Verify docker mount path exists
3. **Search for existing service** - Check kubernetes/ manifests for target service
4. **Document current state** - If service exists, ask user for migration intent

## Discovery & Requirements Extraction

**PURPOSE**: Extract *what* needs deployment, NOT *how* to structure in Kubernetes.

**Locate Service:**

- Search docker mount: `rg --files -g "*docker-compose*"`
- If not found, request exact path from user

**Extract Requirements (NOT Architecture):**

- Read docker-compose.yml, .env files, override files, config files
- Extract ONLY: container images/versions, environment variables, volume paths, port exposures,
  service dependencies, resource requirements, health check commands
- Ignore docker-compose service boundaries and structure

**Data Persistence Analysis:**

- List volume mount paths (ignore docker volume names)
- Identify persistence needs: config vs data vs cache
- Document size requirements and access patterns
- Plan Kubernetes storage strategy: RWO/RWX, Ceph/NFS

## Research Strategy

**MANDATORY SEQUENCE - Complete ALL steps before implementation:**

### 1. Context7 Documentation (FIRST STEP)

- `resolve-library-id` for "bjw-s app-template" or "app-template"
- `get-library-docs` with resolved library ID
- Extract: app-template patterns, controller structure, persistence patterns, networking configs,
  security contexts, health probe configs
- Use Context7 immediately for ANY unclear concepts

### 2. Local Repository Analysis

- Search: `rg -l "app-template" kubernetes/apps/*/*/helmrelease.yaml`
- Read 3+ similar HelmReleases for pattern analysis
- Read corresponding kustomization.yaml, ks.yaml, pvc.yaml files
- Document: controller patterns, storage strategies (RWO/RWX, advancedMounts), networking (HTTPRoute
  usage), security contexts

### 3. OctoCode External Research

- `githubViewRepoStructure` for onedr0p/home-ops kubernetes/apps
- Parallel `githubSearchCode` queries: [$ARGUMENTS, "app-template", "controllers", "persistence",
  "route"]
- `githubGetFileContent` for specific helmrelease.yaml examples
- Cross-reference findings against Context7 documentation

### 4. App-Scout Chart Discovery

- Run `./scripts/app-scout.sh discover $ARGUMENTS`
- Assess dedicated charts vs app-template patterns
- Use for chart availability assessment ONLY

### 5. Validation Cross-Check

- Validate OctoCode findings against Context7 docs
- Ensure patterns align with current app-template best practices
- Context7 is source of truth for conflicts

## Architecture Design

**Service Separation Decision Rules:**

- **Separate HelmReleases IF**: Independent database, different lifecycle, different resources, can
  function independently
- **Same HelmRelease, Separate Controllers IF**: Tightly coupled services, shared config/secrets,
  similar resources, part of same stack
- **Same Controller, Multiple Containers IF**: Sidecar pattern, shared network namespace, init
  container dependencies, shared storage

**Deployment Pattern Selection:**

| Use Dedicated Chart              | Use App-Template                |
| -------------------------------- | ------------------------------- |
| Official maintained chart exists | Simple single-container service |
| Complex configuration            | Custom configuration needs      |
| Multiple interdependent services | Homelab-specific customizations |
| Database clustering              | Need fine-grained control       |

**Storage Strategy:**

| Use NFS                  | Use Rook Ceph          | Use Local                |
| ------------------------ | ---------------------- | ------------------------ |
| Large media (>10GB)      | Database storage       | Temporary/cache data     |
| Shared across pods       | High-performance needs | Single-node requirements |
| Existing Nezuko NFS data | Replicated storage     |                          |

**Network Exposure:**

| HTTPRoute             | ClusterIP Service    | LoadBalancer              |
| --------------------- | -------------------- | ------------------------- |
| Web interface         | Internal-only access | Non-HTTP protocols (rare) |
| External access       | API endpoints        | User explicitly requests  |
| HTTPS/TLS termination | Database connections |                           |

**Volume Mounting Strategy:**

| Pattern        | When to Use                                | Requirements                           |
| -------------- | ------------------------------------------ | -------------------------------------- |
| advancedMounts | RWO volumes, specific controller targeting | REQUIRED for RWO, `strategy: Recreate` |
| globalMounts   | RWX volumes, ConfigMaps, shared data       | Compatible with `RollingUpdate`        |

**App-Template Configuration:**

- OCIRepository: `oci://ghcr.io/bjw-s-labs/helm/app-template`
- Version: Match existing apps from repository analysis
- Controller structure: Based on Context7 + local examples (NOT docker-compose)
- Storage: Apply RWO/RWX patterns from research
- Networking: Use HTTPRoute/service patterns from repository

**Namespace Selection:**

- Analyze: `ls -d kubernetes/apps/*/`
- Follow semantic grouping or justify new namespace

**Directory Structure:**

Single Service Pattern:

```txt
kubernetes/apps/<namespace>/$ARGUMENTS/
├── ks.yaml               # Kustomization with targetNamespace
├── kustomization.yaml    # Resource list
└── app/
    ├── helmrelease.yaml
    ├── ocirepository.yaml
    ├── secret.sops.yaml   (if needed)
    ├── httproute.yaml     (if needed)
    └── pvc.yaml           (if needed)
```

Multi-Service Pattern (Separate Databases):

```txt
kubernetes/apps/<namespace>/$ARGUMENTS/
├── ks.yaml
├── kustomization.yaml
├── app/
│   ├── helmrelease.yaml
│   ├── ocirepository.yaml
│   ├── secret.sops.yaml
│   ├── httproute.yaml
│   └── pvc.yaml
└── database/
    ├── helmrelease.yaml
    ├── secret.sops.yaml
    └── pvc.yaml
```

## Implementation Protocol

**Repository Structure:**

1. Create directory: `kubernetes/apps/<namespace>/$ARGUMENTS/`
2. Generate kustomization.yaml with resource list
3. Add to parent namespace kustomization

**Core Deployment (Context7 + OctoCode Patterns):**

- Create ocirepository.yaml: `url: oci://ghcr.io/bjw-s-labs/helm/app-template`, version from
  research
- Create helmrelease.yaml with:
  - YAML language server schema (Flux schemas)
  - Controllers structure from Context7 docs
  - Service definitions matching controller names
  - Resource requests/limits from docker-compose
  - Security context: runAsNonRoot, capabilities drop, readOnlyRootFilesystem
  - Health probes (HTTP preferred, custom for complex apps)
  - Reloader annotation: `reloader.stakater.com/auto: "true"`
  - Volume mounting: advancedMounts for RWO, globalMounts for RWX
  - Deployment strategy: `Recreate` for RWO volumes, `RollingUpdate` for RWX/stateless

**Database Integration:**

- If required: Create separate HelmRelease using dedicated operator
- MariaDB: Use mariadb-operator pattern from kubernetes/apps/kube-system/mariadb-operator/
- PostgreSQL: Use cloudnative-pg pattern from kubernetes/apps/kube-system/cloudnative-pg/
- Redis: Include as controller only if cache, not primary store

**Storage Configuration:**

- Create PVC manifests for persistent data
- Configure subPath mounting for existing data
- Plan data migration from docker volumes

**Secret Management:**

- Create secret.sops.yaml structure
- Use `sops --set` commands for value insertion
- Configure secret integration in helmrelease

**Network Configuration:**

- Create HTTPRoute for external access (if needed)
- Configure service endpoints
- Set up external-dns annotations

**Validation Strategy:**

1. Pre-commit validation: `pre-commit run --files <changed-files>`
2. Flux validation: `./scripts/flux-local-test.sh`
3. Kustomize build test: `kustomize build kubernetes/apps/<namespace>/$ARGUMENTS`

## Migration Execution

**Pre-Migration:**

- Document current docker-compose state
- Backup volume data if critical
- Note current service URLs and access methods

**Gradual Migration:**

- Deploy to K8s alongside docker-compose
- Validate functionality matches
- Migrate DNS/routing when validated
- Remove docker-compose deployment

**Post-Migration:**

- Verify all functionality working
- Check data persistence across pod restarts
- Validate external access and authentication
- Monitor logs for errors

**GitOps Integration:**

- Commit changes to repository
- Monitor Flux reconciliation
- Verify automatic deployment
- Use `task reconcile` for immediate sync

## Output Format

Present complete plan with:

1. **Requirements from Docker Compose**: Images, env vars, volumes, ports, dependencies (NOT
   architecture)
2. **Research Findings**: Context7 insights, local patterns (with file citations), OctoCode
   discoveries, chart availability
3. **Kubernetes Architecture**: Service separation strategy with rationale, controller structure
   from Context7 + repo patterns, explanation of why design differs from docker-compose
4. **Implementation Strategy**: Deployment pattern, storage strategy, networking approach, secret
   management
5. **File Structure**: Complete directory tree matching repository conventions
6. **Migration Checklist**: Step-by-step implementation and validation procedures
7. **Risk Assessment**: Challenges and mitigation strategies

**REMEMBER: This is PLANNING ONLY. Complete ALL research, present complete plan with citations
showing Kubernetes-first design, and wait for user approval before ANY implementation.**
