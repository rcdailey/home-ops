# HelmRepository to OCIRepository Migration Analysis

**Date**: 2025-10-11 **Analysis Method**: Comprehensive scan using Octocode, Tavily, and Context7

## Overview

This document tracks the migration status of HelmRepository resources to OCIRepository in the
home-ops cluster. OCIRepository provides better performance, native container registry integration,
and simplified dependency management.

## Current HelmRepository Inventory

### Repositories in `kubernetes/flux/meta/repos/`

1. **victoriametrics** - `https://victoriametrics.github.io/helm-charts`
2. **node-feature-discovery** - `https://kubernetes-sigs.github.io/node-feature-discovery/charts`
3. **external-secrets** - `https://charts.external-secrets.io`
4. **intel** - `https://intel.github.io/helm-charts/`
5. **external-dns** - `https://kubernetes-sigs.github.io/external-dns`

### Repositories Embedded in HelmRelease Files

1. **grafana** - `https://grafana.github.io/helm-charts`
2. **metrics-server** - `https://kubernetes-sigs.github.io/metrics-server`
3. **cloudnative-pg** - `https://cloudnative-pg.github.io/charts`

## Migration Status

### ✅ Ready for Migration (1)

#### 1. victoriametrics

- **Current**: `https://victoriametrics.github.io/helm-charts`
- **Target**: `oci://ghcr.io/victoriametrics/helm-charts/`
- **Charts Used**:
  - `victoria-metrics-k8s-stack` (observability/victoria-metrics-k8s-stack)
  - `victoria-logs-single` (observability/victoria-logs-single)
  - `grafana` (observability/grafana) - uses victoriametrics repo reference
- **Verification**: Context7 documentation confirms multiple OCI installation examples
- **Status**: Production-ready, fully documented
- **Migration Priority**: HIGH - Most widely used repository in cluster

### ⚠️ Requires Manual Verification (1)

#### 2. node-feature-discovery

- **Current**: `https://kubernetes-sigs.github.io/node-feature-discovery/charts`
- **Target**: `oci://gcr.io/k8s-staging-nfd/charts/node-feature-discovery`
- **Charts Used**: `node-feature-discovery` (kube-system/node-feature-discovery)
- **Verification**: Tavily search found official README mentioning OCI as primary method
- **Status**: OCI mentioned in documentation but not verified by Context7
- **Manual Test Required**:

  ```bash
  helm pull oci://gcr.io/k8s-staging-nfd/charts/node-feature-discovery --version 0.18.1
  ```

- **Migration Priority**: MEDIUM

### ❌ No OCI Support (6)

#### 3. external-secrets

- **Current**: `https://charts.external-secrets.io`
- **Charts Used**: `external-secrets` (kube-system/external-secrets)
- **Verification**: Context7 documentation shows ONLY traditional Helm repo methods
- **Initial Assessment**: INCORRECT - GitHub issue #3208 mentions OCI packages but not in production
- **Status**: No OCI support in official documentation
- **Migration Priority**: N/A - Wait for upstream

#### 4. intel

- **Current**: `https://intel.github.io/helm-charts/`
- **Charts Used**: `intel-device-plugins-gpu` (kube-system/intel-gpu-plugin)
- **Verification**: Context7 returned no Intel Helm chart documentation
- **Status**: Cannot confirm OCI support
- **Migration Priority**: N/A - Requires upstream investigation

#### 5. external-dns

- **Current**: `https://kubernetes-sigs.github.io/external-dns`
- **Charts Used**: `external-dns` (network/cloudflare-dns, dns-private/external-dns,
  network/external-dns)
- **Verification**: Context7 confirms only traditional Helm repo
- **GitHub Issue**: #4630 requests OCI support but NOT implemented
- **Status**: No OCI support
- **Migration Priority**: N/A - Wait for upstream

#### 6. grafana

- **Current**: `https://grafana.github.io/helm-charts`
- **Charts Used**: `grafana` (observability/grafana)
- **Verification**: Context7 shows only traditional Helm repo: `helm repo add grafana
  https://grafana.github.io/helm-charts`
- **Status**: No OCI registry documented
- **GitHub Issue**: #3068 requests OCI support, some charts available but NOT main grafana chart
- **Migration Priority**: N/A - Wait for upstream

#### 7. metrics-server

- **Current**: `https://kubernetes-sigs.github.io/metrics-server`
- **Charts Used**: `metrics-server` (kube-system/metrics-server)
- **Verification**: No Context7 data, Tavily confirmed GitHub issue #1527
- **Status**: Only HTTP Helm repo available
- **Migration Priority**: N/A - Wait for upstream

#### 8. cloudnative-pg

- **Current**: `https://cloudnative-pg.github.io/charts`
- **Charts Used**: `cloudnative-pg` (kube-system/cloudnative-pg)
- **Verification**: Context7 documentation shows only traditional Helm repo methods
- **Status**: No OCI registry available
- **Migration Priority**: N/A - Wait for upstream

## Verification Methodology

### CRITICAL: Factual Verification Requirements

**ALL OCI availability claims MUST be verified through one of these sources:**

1. **Context7 (PRIMARY)** - Official documentation analysis
   - Most reliable source for production-ready OCI support
   - Reveals actual installation methods vs. wishful thinking
   - Example: `mcp__context7__get-library-docs` for chart documentation
   - Shows real OCI installation examples (or lack thereof)

2. **Octocode MCP** - GitHub repository code search
   - Search for actual OCI implementation patterns
   - View repository structure to find ocirepository.yaml files
   - Get file content to see exact patterns
   - Example: Searched onedr0p/home-ops and bjw-s-labs/home-ops for patterns

3. **Tavily Search** - Web search for issues and announcements
   - Find GitHub issues requesting OCI support
   - Identify gaps between requests and implementation
   - Cross-reference claims against documentation
   - Example: Found issue #3208 for external-secrets claiming OCI, but Context7 showed no docs

### Tools Used

1. **Ripgrep (rg)**: Repository file discovery and pattern matching
2. **Octocode MCP**: GitHub repository structure and code search
3. **Tavily Search**: Web search for current documentation and GitHub issues
4. **Context7**: Official documentation analysis for installation methods

### Verification Process

For each repository:

1. Searched codebase for HelmRepository definitions
2. Identified all HelmRelease resources using each repository
3. Searched GitHub repositories for OCI-related code and issues
4. Searched web for recent documentation updates
5. **Critical**: Analyzed official documentation via Context7 for OCI installation examples
6. Cross-referenced findings across all sources

### Verification Hierarchy

**Priority order for OCI support verification:**

1. **Context7** → Official docs showing `helm install oci://` examples = CONFIRMED
2. **Manual Test** → `helm pull oci://registry/chart:version` succeeds = VERIFIED
3. **Octocode** → Multiple repos using ocirepository.yaml for the chart = LIKELY
4. **Tavily/GitHub** → Issues/PRs mentioning OCI = POSSIBLE (needs verification)

**NEVER assume OCI support without Context7 or manual helm verification.**

### Key Finding

Initial web searches suggested more OCI support than actually exists. **Context7 documentation
analysis was the most reliable source**, revealing that only VictoriaMetrics has production-ready,
documented OCI support.

**Example - External Secrets False Positive:**

- Tavily found GitHub issue #3208 mentioning OCI packages at ghcr.io
- Context7 analysis of official docs showed ZERO OCI installation examples
- Conclusion: NOT production-ready despite GitHub mentions

**Example - VictoriaMetrics True Positive:**

- Context7 returned multiple code snippets with `helm install
  oci://ghcr.io/victoriametrics/helm-charts/`
- Official documentation explicitly documents OCI installation
- Conclusion: Production-ready and documented

## Migration Impact Assessment

### Immediate Migration Candidates

- **victoriametrics**: 3 HelmRelease resources affected
  - kubernetes/apps/observability/victoria-metrics-k8s-stack/helmrelease.yaml
  - kubernetes/apps/observability/victoria-logs-single/helmrelease.yaml
  - kubernetes/apps/observability/grafana/helmrelease.yaml (references victoriametrics repo)

### Blocked Migrations

- **6 repositories** cannot migrate until upstream projects publish OCI charts
- Affects **11+ HelmRelease resources** across the cluster

## Migration Strategy

### Phase 1: VictoriaMetrics (COMPLETED ✅)

**Date Completed**: 2025-10-11

**Implementation Pattern** (based on onedr0p/home-ops):

- Each app owns its `ocirepository.yaml` (NOT centralized in flux/meta/repos)
- HelmRelease uses `chartRef: {kind: OCIRepository, name: app-name}` (no namespace)
- OCIRepository structure: `layerSelector`, `ref.tag`, `url: oci://registry/path/chart-name`

**Files Created:**

1. `kubernetes/apps/observability/victoria-metrics-k8s-stack/ocirepository.yaml`
2. `kubernetes/apps/observability/victoria-logs-single/ocirepository.yaml`

**Files Modified:**

1. `kubernetes/apps/observability/victoria-metrics-k8s-stack/helmrelease.yaml` - Changed to
   `chartRef`
2. `kubernetes/apps/observability/victoria-metrics-k8s-stack/kustomization.yaml` - Added
   ocirepository.yaml
3. `kubernetes/apps/observability/victoria-logs-single/helmrelease.yaml` - Changed to `chartRef`
4. `kubernetes/apps/observability/victoria-logs-single/kustomization.yaml` - Added
   ocirepository.yaml
5. `CLAUDE.md` - Added OCIRepository directives and preference policy

**Files Removed:**

1. `kubernetes/flux/meta/repos/victoriametrics.yaml` (centralized HelmRepository removed)

**Validation:**

- ✅ flux-local-test: 103 tests passed
- ✅ pre-commit: All checks passed

**Key Learning**: Initial approach was to centralize OCIRepository like HelmRepository was, but
research into popular repos (onedr0p, bjw-s-labs) revealed the correct pattern is per-app ownership.

### Phase 2: Node Feature Discovery (Pending Verification)

1. Manually verify OCI support: `helm pull
   oci://gcr.io/k8s-staging-nfd/charts/node-feature-discovery`
2. If successful, migrate following Phase 1 pattern
3. Document any version compatibility issues

### Phase 3: Wait for Upstream

- Monitor GitHub issues for remaining 6 repositories
- Re-evaluate quarterly for new OCI support
- Consider contributing to upstream projects if needed

## References

- [VictoriaMetrics Helm Charts](https://github.com/VictoriaMetrics/helm-charts)
- [Node Feature Discovery](https://github.com/kubernetes-sigs/node-feature-discovery)
- [External Secrets Issue #3208](https://github.com/external-secrets/external-secrets/issues/3208)
- [External DNS Issue #4630](https://github.com/kubernetes-sigs/external-dns/issues/4630)
- [Grafana Helm Charts Issue #3068](https://github.com/grafana/helm-charts/issues/3068)
- [Metrics Server Issue #1527](https://github.com/kubernetes-sigs/metrics-server/issues/1527)

## Lessons Learned

1. **GitHub Issues Are Not Documentation**: Issues requesting features don't mean features exist
2. **Web Search Can Be Misleading**: Found references to OCI packages that aren't production-ready
3. **Context7 Is Most Reliable**: Official documentation analysis revealed true support status
4. **Manual Verification Essential**: Always test `helm pull oci://` before migrating
5. **Pattern Research Critical**: Don't assume centralized structure - check popular repos for
   patterns
6. **OCIRepository Is Per-App**: Each app owns its ocirepository.yaml, not centralized like
   HelmRepository

## OCIRepository Migration Pattern

Based on onedr0p/home-ops and bjw-s-labs/home-ops analysis:

### Directory Structure

```txt
kubernetes/apps/<namespace>/<app>/
├── ocirepository.yaml    # NEW: Per-app OCI source
├── helmrelease.yaml      # MODIFIED: Uses chartRef
├── kustomization.yaml    # MODIFIED: Includes ocirepository.yaml
└── ...
```

### OCIRepository Template

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/ocirepository-source-v1.json
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: app-name
spec:
  interval: 15m
  layerSelector:
    mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
    operation: copy
  ref:
    tag: 1.2.3
  url: oci://registry.example.com/path/chart-name
```

### HelmRelease Changes

**Before (HelmRepository):**

```yaml
spec:
  chart:
    spec:
      chart: app-name
      version: 1.2.3
      sourceRef:
        kind: HelmRepository
        name: repo-name
        namespace: flux-system
```

**After (OCIRepository):**

```yaml
spec:
  chartRef:
    kind: OCIRepository
    name: app-name  # No namespace (same namespace)
```

## Next Steps

1. ✅ Document this analysis
2. ✅ Migrate victoriametrics to OCIRepository
3. ⏳ Manually verify node-feature-discovery OCI support
4. ⏳ Set quarterly reminder to check upstream progress (external-dns, grafana, metrics-server, etc.)
5. ✅ Document OCIRepository pattern in CLAUDE.md
