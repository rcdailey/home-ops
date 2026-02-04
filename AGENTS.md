# Home-Ops Directives

## Tier 1: Breaking Rules

These rules prevent immediate cluster failures. Violations cause crashes, data corruption, or GitOps
drift.

### GitOps Mindset

**Every cluster change MUST flow through git.** Imperative commands are diagnostic only.

- **NEVER run git commit/push without explicit user request** - GitOps requires user commits for
  accountability
- **NEVER use kubectl apply/create/patch** - Bypasses GitOps, creates configuration drift. Use
  manifest changes only.
- **NEVER use kubectl delete as a fix** - Deleting resources (jobs, pods, PVCs) treats symptoms, not
  causes. Find the manifest issue and fix it. Exception: cleanup after root cause is fixed.
- **NEVER adjust health probes to fix failures** - Probes detect problems, they don't cause them.
  Investigate WHY the probe fails (resource exhaustion, slow startup, missing deps).
- **Cluster investigation is read-only** - NEVER use kubectl apply/create/delete/patch, helm
  install/upgrade/uninstall, flux suspend/resume, or talosctl apply-config/upgrade/reboot/reset.

### Troubleshooting Approach

1. **Query**: Gather symptoms via subagent (alerts, logs, events, pod status)
2. **History**: `git log -p --follow -- path/to/file.yaml` for recent changes
3. **Analyze**: Read manifests, check CRD specs, verify dependencies
4. **Research**: Subagent for reference repos, Context7, upstream docs
5. **Fix**: Modify manifests to address root cause
6. **Validate**: `pre-commit run --files <changed-files>`

Recurring issues indicate incomplete root cause analysis.

**Token-efficient kubectl patterns:**

- Use `--no-headers`, `-o name`, `| head -n 50` for large result sets
- Pipe verbose output through `rg` to extract relevant lines
- Write to /tmp for iteration: `kubectl describe pod foo -n bar > /tmp/pod.txt` then grep multiple
  times
- Use label selectors, field selectors, jsonpath to reduce output
- Avoid `kubectl get all`, unfiltered logs, full resource dumps

**Ephemeral test pods** (connectivity/DNS/network debugging):

```bash
kubectl run dns-test --rm -i --restart=Never --image=busybox:stable -- nslookup kubernetes.default
```

MUST use `--rm --restart=Never`. MUST NOT deploy services or use privileged contexts.

### Storage, Volumes, and Resource Patterns

- **RWO volumes MUST use strategy: Recreate** - RollingUpdate causes Multi-Attach errors during pod
  transitions (ceph-block is RWO)
- **RWO volumes REQUIRE advancedMounts** - Single-pod exclusive access requires explicit
  controller/container specification
- **Jobs/CronJobs with RWO PVCs MUST use native sidecar pattern** - initContainers with
  restartPolicy: Always prevents Multi-Attach errors on subsequent runs
- **NEVER specify metadata.namespace in app resources** - Breaks namespace inheritance from parent
  kustomization.yaml
- **App ks.yaml (Flux Kustomization) uses spec.targetNamespace** - Exception to inheritance rule,
  NOT metadata.namespace
- **NEVER use chart.spec.sourceRef for app-template** - Use chartRef (references OCIRepository).
  Exception: External HelmRepository charts may use chart.spec.sourceRef.
- **chartRef REQUIRES namespace for cross-namespace OCIRepository references** - App-template
  OCIRepository is in flux-system namespace; all HelmReleases MUST specify namespace: flux-system

### Secrets and Configuration

- **NEVER use secret.sops.yaml files** - Obsolete pattern replaced by ExternalSecret with Infisical
  ClusterSecretStore
- **NEVER use postBuild.substituteFrom for app secrets** - Timing race condition with ExternalSecret
  creation causes failures
- **ONLY use postBuild.substituteFrom for**: cluster-secrets, email-secrets (pre-existing SOPS
  secrets managed centrally)
- **NEVER use raw ConfigMap resources** - ALWAYS use configMapGenerator in kustomization.yaml with
  files from config/ subdirectory
- **NEVER inline VRL source in vector.yaml** - Separate VRL file required for testing and validation
- **ALWAYS include test data for VRL validation** - Use ./scripts/test-vector-config.py for
  validation

### Scaling

- KEDA ScaledObjects create HPAs that continuously enforce replica counts
- Manual `kubectl scale` is overridden by KEDA HPA when trigger is active
- To manually scale: pause ScaledObject first (`autoscaling.keda.sh/paused: "true"` annotation)

## Tier 2: Conventions

Consistency patterns for maintainability and clarity.

### Configuration Standards

- ALWAYS use chartRef (see Tier 1: Storage, Volumes, and Resource Patterns)
- ALWAYS include appropriate `# yaml-language-server:` directive at top of YAML files
- ALWAYS use reloader.stakater.com/auto: "true" for ALL apps (NEVER use targeted annotations)
- ALWAYS use rootless containers (security requirement)
- ALWAYS check existing applications before making changes
- PREFER YAML defaults by omission over explicit configuration (minimal config improves
  maintainability)
- Add comments explaining WHY special approaches were needed (e.g., chart limitations, upstream
  issues)
- NEVER use cluster-apps- prefix in service/app names
- NEVER invent new patterns or adopt conventions from other repositories
- NEVER reference real homelab domain names in documentation or config examples (use
  `${SECRET_DOMAIN}` in YAML manifests)
- Internal cluster hostnames: ONLY use `service.namespace`, without ending with `svc.cluster.local`
- Service naming: Single `service:` entry uses HelmRelease name only; multiple entries append the
  service key (e.g., `plex` vs `plex-main`, `plex-api`)
- Controller naming: Primary controller MUST match HelmRelease name (e.g., `controllers: plex:` for
  release `plex`). This produces deployment `plex` instead of `plex-main`. App-template avoids
  `{release}-{release}` duplication when controller matches release.
- Primary: `ghcr.io/home-operations/*` containers (semantically versioned, rootless, multi-arch)
- Secondary: `ghcr.io/onedr0p/*` containers (if home-operations unavailable)
- Avoid: `ghcr.io/hotio/*` and containers using s6-overlay, gosu
- NEVER use latest, rolling, or non-semantic tags (semantic versioning required)
- SHA256 digests: Automatically added by renovatebot
- Container command/args: Use bracket notation `command: ["cmd", "arg"]` instead of multi-line dash
  format for consistency
- ALWAYS use America/Chicago (or equivalent representation) for timezone if needed.
- SMTP: `smtp-relay.network:587` (no auth) - never configure app-specific SMTP credentials

### Health Probes

- Probes default to off in app-template; only specify probes you need
- Liveness: ALWAYS enable with simple httpGet returning 200 (e.g., `/status`, `/health`, `/ping`)
- Readiness: OMIT for single-replica services (readiness controls traffic routing, irrelevant
  without HA). Only add readiness for multi-replica deployments where it should perform a more
  comprehensive check than liveness.
- Startup: OMIT unless slow initialization requires extended startup time
- Omit default values (initialDelaySeconds: 0, periodSeconds: 10, timeoutSeconds: 1,
  failureThreshold: 3)

### Security and Networking

- OIDC client IDs: Hardcode as app name in env vars (not secret); only client secret needs Infisical
- HTTPRoute ONLY for all routing (never Ingress)
- NEVER use kubectl port-forward under ANY circumstances (alternatives: kubectl exec, debug pods,
  HTTPRoute exposure)
- NEVER configure External-DNS on HTTPRoutes (Gateways only)
- NEVER create LoadBalancer without explicit user discussion
- Route backendRefs: Use full service name (e.g., radarr-app), not identifier (e.g., app)
- NEVER use wildcards for SecurityPolicy headers (always explicit headers)
- NEVER specify explicit timeouts/intervals without justification (use Flux defaults)
- Container securityContext: runAsUser/runAsGroup 1000, runAsNonRoot true, allowPrivilegeEscalation
  false, readOnlyRootFilesystem true, capabilities drop ALL
- Pod securityContext: fsGroup 1000, fsGroupChangePolicy OnRootMismatch

### Database and Logging

- NEVER share databases between apps (dedicated instances per app)
- Use CloudNativePG for PostgreSQL, MariaDB Operator for MariaDB
- NEVER create custom equivalents to standard Vector fields (message, timestamp, level, severity,
  host, source_type)
- VRL regex: Prefer non-greedy `.*?` over greedy `.*`
- Sidecar pattern: Regular containers for Deployments, initContainers with restartPolicy: Always for
  Jobs/CronJobs

### Documentation

- Validate markdown changes with `markdownlint-cli2` before committing
- Links: reference-style `[text][anchor]` with definitions at section end (not inline)
- NEVER use bold text as heading replacement - use actual `##` headings
- Hard-wrap at column 100
- Blank line required between headings, lists, code blocks, and other elements

### Skills

- `renovate`: REQUIRED when creating, modifying, or auditing Renovate configuration

### Upstream Issue Writeups

When root cause analysis identifies an issue requiring upstream fixes (container images, charts,
external projects):

1. MUST load the `gh-gist` skill
2. MUST read `docs/issues/TEMPLATE.md` for structure
3. Create `docs/issues/{component}-{brief-description}.md` following the template
4. Upload as a secret gist for sharing

Files in `docs/issues/*.md` are gitignored (except TEMPLATE.md). Gists are the sharing mechanism;
local files are for iterative editing before upload.

## Tier 3: Reference

Implementation patterns, operational workflows, and environment details.

This repository is at `rcdailey/home-ops` in github.

### Reference Repositories

Popular repositories to use as reliable reference implementations. You MUST reference these
repositories often as documentation.

- onedr0p/home-ops
- bjw-s-labs/home-ops
- buroa/k8s-gitops
- m00nwtchr/homelab-cluster

### API Versions

- ExternalSecret: `external-secrets.io/v1`

### Repository and File Organization

Pattern: `kubernetes/apps/namespace/app/`

```txt
kubernetes/apps/{namespace}/{app}/
  ks.yaml             Flux Kustomization (spec.targetNamespace)
  kustomization.yaml  Kustomize resources list, components
  helmrelease.yaml    HelmRelease (chartRef or chart.spec.sourceRef)
  pvc.yaml            PersistentVolumeClaims
  externalsecret.yaml Infisical secrets
  config/             Files for configMapGenerator

docs/
  architecture/       System design, rationale for technology choices
  decisions/          ADRs - read TEMPLATE.md before creating/editing
  issues/             Upstream issue writeups (gitignored, shared via gists)
  memory-bank/        Ephemeral context, temporary workarounds (remove when stale)
  runbooks/           Step-by-step operational procedures
  troubleshooting/    Historical investigations with root cause analysis
```

- Namespace directories MUST match actual namespace names exactly
- Use flat directory structure for YAML files
- Use subdirectory for files used in configMapGenerator
- Use straightforward naming matching directory structure (e.g., mariadb-operator NOT
  cluster-apps-mariadb-operator)
- App `ks.yaml` file (Flux Kustomization) must be listed in parent kustomization.yaml resources
- App `kustomization.yaml` lists resources: `helmrelease.yaml`, `pvc.yaml`, `externalsecret.yaml`,
  etc
- ALWAYS include ./pvc.yaml in kustomization.yaml resources
- PVC naming: Primary PVC matches app name, additional PVCs use {app}-{purpose}

### App Templates

Copy patterns from exemplary apps rather than using synthetic templates. These apps follow all
Tier 1 and Tier 2 conventions:

**Canonical example (start here):** `kubernetes/apps/default/bookstack/`

- Complete app-template implementation with all best practices
- Files: ks.yaml, kustomization.yaml, helmrelease.yaml, pvc.yaml, externalsecret.yaml
- Patterns: chartRef, strategy: Recreate, advancedMounts, security context, liveness-only probe

**ConfigMapGenerator pattern:** `kubernetes/apps/media/plex/`

- Uses config/ subdirectory with configMapGenerator and disableNameSuffixHash: true

**External chart pattern:** `kubernetes/apps/default/headlamp/`

- Uses chart.spec.sourceRef with local HelmRepository (not app-template)

#### File Requirements

**ks.yaml (Flux Kustomization):**

- `targetNamespace` sets namespace (NOT metadata.namespace)
- `dependsOn: global-config` required if using cluster-secrets substitution
- `dependsOn: rook-ceph-cluster` required if using ceph storage
- `postBuild.substitute.APP` required if using volsync component

**kustomization.yaml (Kustomize):**

- NO namespace field (inherited from parent ks.yaml)
- List all resources explicitly
- Components (volsync, nfs-scaler) are optional based on app needs

**helmrelease.yaml (App-Template):**

- `chartRef.namespace: flux-system` REQUIRED (OCIRepository location)
- Controller name MUST match HelmRelease metadata.name
- `strategy: Recreate` REQUIRED for RWO volumes
- ALWAYS use advancedMounts (format: `{controller}: {container}: - path: /path`)

**helmrelease.yaml (External Chart):**

- Use `chart.spec.sourceRef` with local HelmRepository defined in same directory
- See headlamp for example with helmrepository.yaml alongside helmrelease.yaml

**pvc.yaml:**

- Primary PVC name matches app name; additional PVCs use {app}-{purpose}
- Storage types: ceph-block (RWO, Recreate), ceph-filesystem (RWX, RollingUpdate), NFS (RWX,
  RollingUpdate, media/large files)

**externalsecret.yaml:**

- Path format: `/namespace/app-name/secret-name`
- Add secrets: `just infisical add-secret /namespace/app/key "value"`

### Additional Patterns

**Source repositories:**

- GitRepository (Kustomization sources): ALWAYS in flux/meta/repos - ks.yaml can't deploy its own
  source
- OCIRepository/HelmRepository (chart sources): Shared (2+ apps) in flux/meta/repos with `namespace:
  flux-system`; single-use local to app, omit namespace (inherits from ks.yaml)

**Kustomize files:**

- Parent kustomization.yaml: Sets namespace, lists app ks.yaml files, includes components (common,
  drift-detection)
- App kustomization.yaml: Lists resources, may include components (volsync), may define
  configMapGenerator
- Stable naming (disableNameSuffixHash: true): ONLY for cross-resource dependencies (Helm
  valuesFrom, persistence.name)

**Volsync component:**

Add to app `kustomization.yaml` components; in `ks.yaml` add `postBuild.substituteFrom:
cluster-secrets`. Variables: `APP` (required), `VOLSYNC_PVC` (default: APP),
`VOLSYNC_STORAGECLASS`/`VOLSYNC_SNAPSHOTCLASS` (default: ceph-block/csi-ceph-blockpool). For
ceph-filesystem PVCs: set both to ceph-filesystem/csi-ceph-filesystem

**Secrets priority:** envFrom > env.valueFrom > HelmRelease valuesFrom

### Multi-Controller Apps

For apps with multiple processes (main + worker + redis pattern):

**Reference implementation:** `kubernetes/apps/default/immich/`

- Define separate controllers for each process (immich, machine-learning, redis)
- Each controller gets its own service with `controller:` reference
- Use advancedMounts to map persistence per-controller: `{controller}: {container}: - path:`
- Each controller can have independent strategy, replicas, and security context

### Intel GPU (DRA)

For apps requiring Intel GPU acceleration:

**Reference implementation:** `kubernetes/apps/default/immich/` (machine-learning controller)

- ks.yaml: Add `dependsOn: intel-gpu-resource-driver` (namespace: kube-system)
- Pod: nodeSelector `feature.node.kubernetes.io/custom-intel-gpu: "true"`
- Pod: resourceClaims with resourceClaimTemplateName referencing app-specific ResourceClaimTemplate
- Container: resources.claims to request the GPU
- Values: resourceClaimTemplates with deviceClassName: gpu.intel.com
- OpenVINO: Set OPENVINO_DEVICE: GPU for hardware acceleration

### Operational Workflows

**GitOps flow:** Modify manifests -> User commits/pushes -> Flux auto-applies -> Optional just
reconcile

**Commands:**

```bash
# Setup
mise trust .mise.toml && mise install

# Reconcile cluster
just reconcile

# Flux operations
flux reconcile hr NAME -n NAMESPACE --force
flux reconcile hr NAME -n NAMESPACE --force --with-source  # Refresh source
flux reconcile hr NAME -n NAMESPACE --force --reset        # Clear retry backoff

# Helm (check values before configuring)
helm show values CHART
helm template RELEASE CHART

# Talos (one node at a time)
just talos generate-config                    # After config changes, run once
just talos apply-node IP=192.168.1.X          # Apply to each node sequentially
talosctl SUBCOMMAND OPTIONS -n NODEIP         # -n toward end
```

Scripts in `./scripts/` - use `--help` for usage:

- query-vm.py: VictoriaMetrics queries, alerts, discovery
- query-victorialogs.py: Log queries
- ceph.sh: Ceph commands via rook-ceph-tools
- test-vector-config.py: Vector VRL validation (required for Vector changes)
- validate-vmrules.sh: VMRule syntax validation
- icon-search.py: Search dashboard icons for Homepage services

**Conventional commits (MANDATORY path-based):**

- ci: `.github/workflows/**`, `.justfiles/**`, .justfile
- build: renovate.json5, `.renovate/**`
- chore: .editorconfig, .gitignore, .yamllint.yaml, .markdownlint-cli2.yaml, .pre-commit-config.yaml
- docs: `*.md`, `docs/**`, LICENSE, SECURITY.md, CODEOWNERS
- feat (k8s): New apps/services (new kubernetes/apps/namespace/app/ directories)
- fix (k8s): Bug fixes, crash loops, probe failures, resource issues, alert resolutions
- refactor (k8s): Resource reorganization, no behavior change
- feat/fix (scripts): Script capabilities/bug fixes
- Breaking (type!:): API/CRD upgrades, incompatible Helm upgrades, storage migrations
- Examples: fix(plex): resolve crash loop, feat(bookstack): add wiki documentation app

### Environment and Infrastructure

**Stack components:**

- OS: Talos Linux
- Orchestration: Kubernetes with Flux v2 GitOps
- Secrets: SOPS with Age encryption, External Secrets Operator with Infisical
- Storage: Rook Ceph (distributed), NFS from Nezuko, Garage S3
- Automation: just, mise, talhelper

**Alerting:**

- Pushover: VMAlertmanager sends alerts to Pushover app for mobile notifications
- Healthchecks.io: Dead man's switch; Watchdog alert pings external endpoint every 5 minutes. If
  cluster or monitoring stack goes down, Healthchecks.io detects missing pings and alerts via
  Pushover.

**Network topology:**

- Main subnet: 192.168.1.0/24
- BGP subnet (Cilium LoadBalancers): 192.168.50.0/24
- Gateway (Unifi UDMP): 192.168.1.1
- Kubernetes API: 192.168.1.70
- LoadBalancer IPs (Cilium IPAM): 192.168.50.71-.99 (infrastructure), 192.168.50.100+ (applications)

**Cluster nodes:**

- Control plane: hanekawa (192.168.1.63), marin (192.168.1.59), sakura (192.168.1.62)
- Workers: lucy (192.168.1.54), nami (192.168.1.50)

**Storage backends:**

- Rook Ceph: Distributed block/filesystem storage across cluster nodes
- NFS (Nezuko 192.168.1.58): Media (100Ti), Photos (10Ti)
- Garage S3 (192.168.1.58:3900): Region garage, buckets: postgres-backups, volsync-backups,
  bookstack-backups
- CloudNativePG: Barman WAL archiving to s3://postgres-backups/{cluster}/
- Ceph toolbox: kubectl exec -n rook-ceph deploy/rook-ceph-tools -- [ceph status | rbd COMMAND]

**Intel GPU support:**

- DRA via ResourceClaimTemplate with deviceClassName: gpu.intel.com
- OpenVINO: Set OPENVINO_DEVICE: GPU for hardware acceleration

**query-vm.py reference** (use `--json` before subcommand for machine output):

```bash
# Container metrics (namespace, pod-regex, container; default --from 7d)
./scripts/query-vm.py cpu media 'plex.*' plex
./scripts/query-vm.py memory default 'homepage.*' app --from 24h

# Raw PromQL
./scripts/query-vm.py query 'up{job="kubelet"}'
./scripts/query-vm.py query 'rate(http_requests_total[5m])' --from 1h --step 5m

# Discovery
./scripts/query-vm.py labels                  # All label names
./scripts/query-vm.py labels namespace        # Values for label
./scripts/query-vm.py metrics --filter cpu    # Find metrics by pattern

# Alerts (current state from vmalert)
./scripts/query-vm.py alerts                  # Firing (excludes Watchdog/InfoInhibitor)
./scripts/query-vm.py alerts --state all      # All states
./scripts/query-vm.py alert <name>            # Detail for specific alert
./scripts/query-vm.py rules                   # All alert rules

# Alerts (historical from VictoriaMetrics)
./scripts/query-vm.py alerts --from 24h       # Alerts that fired in period
./scripts/query-vm.py alert <name> --from 24h # Historical alert details with firing periods
```

**Diagnostic PromQL recipes** (use with `query` subcommand, replace NS/POD/C):

```promql
# Restarts (raw counter; query first to avoid increase() counter-reset confusion)
kube_pod_container_status_restarts_total{namespace="NS",pod=~"POD.*"}

# OOMKilled pods
kube_pod_container_status_last_terminated_reason{reason="OOMKilled",namespace="NS"}

# CrashLoopBackOff pods
kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff",namespace="NS"}

# Exit code (137=SIGKILL/OOM, 143=SIGTERM, 1=app error)
kube_pod_container_status_last_terminated_exitcode{namespace="NS",pod=~"POD.*"}

# CPU throttling % (requires CPU limits set)
sum(increase(container_cpu_cfs_throttled_periods_total{namespace="NS",pod=~"POD.*",container="C"}[1h])) / sum(increase(container_cpu_cfs_periods_total{namespace="NS",pod=~"POD.*",container="C"}[1h])) * 100
```

### New App Checklist

1. Create directory `kubernetes/apps/{namespace}/{app}/`
2. Create ks.yaml with correct path, targetNamespace, dependencies
3. Create kustomization.yaml listing all resources
4. Create helmrelease.yaml with correct chartRef pattern
5. Create pvc.yaml if stateful (match storage type to strategy)
6. Create externalsecret.yaml if secrets needed
7. Add ks.yaml to parent `kubernetes/apps/{namespace}/kustomization.yaml`
8. Add secrets to Infisical: `just infisical add-secret /namespace/app/key "value"`
