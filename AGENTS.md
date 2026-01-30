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
- **Perform extended kubectl/research in subagents** - Use Task tool for multi-step diagnostics
  (describe, logs, events, explain). Keep main context focused on analysis and fixes.

### Troubleshooting Approach

1. **Query**: Gather symptoms via subagent (alerts, logs, events, pod status)
2. **History**: `git log -p --follow -- path/to/file.yaml` for recent changes
3. **Analyze**: Read manifests, check CRD specs, verify dependencies
4. **Research**: Subagent for reference repos, Context7, upstream docs
5. **Fix**: Modify manifests to address root cause
6. **Validate**: `pre-commit run --files <changed-files>`

Recurring issues indicate incomplete root cause analysis.

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

- Liveness and Readiness: ALWAYS enable both
- Startup: OMIT unless slow initialization requires it
- httpGet with app health endpoint (e.g., `/ping`, `/health`) preferred over TCP
- Use YAML anchor (`&probes` / `*probes`) to share spec between liveness and readiness
- Omit default values (initialDelaySeconds: 0, periodSeconds: 10, timeoutSeconds: 1,
  failureThreshold: 3)

### Security and Networking

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

#### ks.yaml (Flux Kustomization)

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/kustomization-kustomize-v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app example-app
spec:
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  dependsOn:
  - name: rook-ceph-cluster
    namespace: rook-ceph
  - name: global-config
    namespace: flux-system
  interval: 1h
  path: ./kubernetes/apps/{namespace}/{app}
  prune: true
  retryInterval: 2m
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: {namespace}  # Sets namespace for ALL resources
  timeout: 5m
  wait: false
  postBuild:
    substituteFrom:
    - kind: Secret
      name: cluster-secrets
    substitute:
      APP: example-app
      VOLSYNC_PVC: example-app  # Only if using volsync component
```

- `targetNamespace` sets namespace (NOT metadata.namespace)
- `dependsOn: global-config` required if using cluster-secrets substitution
- `dependsOn: rook-ceph-cluster` required if using ceph storage
- `postBuild.substitute.APP` required if using volsync component

#### kustomization.yaml (Kustomize)

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization.json
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
components:
- ../../../components/volsync      # Optional: backup replication
- ../../../components/nfs-scaler   # Optional: KEDA scaler for NFS
resources:
- ./externalsecret.yaml
- ./helmrelease.yaml
- ./pvc.yaml
```

- NO namespace field (inherited from parent)
- List all resources explicitly
- Components are optional based on app needs

#### helmrelease.yaml (App-Template)

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/helmrelease-helm-v2.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: example-app
spec:
  interval: 1h
  chartRef:
    kind: OCIRepository
    name: app-template
    namespace: flux-system  # REQUIRED - OCIRepository lives in flux-system
  values:
    controllers:
      example-app:  # MUST match HelmRelease metadata.name
        strategy: Recreate  # REQUIRED for RWO volumes
        annotations:
          reloader.stakater.com/auto: "true"
        pod:
          securityContext:
            fsGroup: 1000
            fsGroupChangePolicy: OnRootMismatch
        containers:
          app:
            image:
              repository: ghcr.io/home-operations/example
              tag: 1.0.0
            env:
              TZ: America/Chicago
            securityContext:
              runAsUser: 1000
              runAsGroup: 1000
              runAsNonRoot: true
              allowPrivilegeEscalation: false
              readOnlyRootFilesystem: true
              capabilities:
                drop: [ALL]
            probes:
              liveness: &probes
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /ping  # App-specific health endpoint
                    port: *port
              readiness: *probes
            resources:
              requests:
                cpu: 100m
                memory: 256Mi
              limits:
                memory: 1Gi

    service:
      app:
        controller: example-app
        ports:
          http:
            port: 8080

    persistence:
      config:
        existingClaim: example-app
        advancedMounts:
          example-app:  # Controller name
            app:        # Container name
            - path: /config
      tmp:
        type: emptyDir
        advancedMounts:
          example-app:
            app:
            - path: /tmp

    route:
      app:
        hostnames: ["example.${SECRET_DOMAIN}"]
        parentRefs:
        - name: internal
          namespace: network
          sectionName: https
```

- `chartRef.namespace: flux-system` REQUIRED (OCIRepository location)
- Controller name MUST match HelmRelease name
- `strategy: Recreate` REQUIRED for RWO volumes (prevents Multi-Attach errors)
- ALWAYS use `advancedMounts` (even for RWX/emptyDir for consistency)
- Format: `advancedMounts: {controller}: {container}: - path: /path`

#### helmrelease.yaml (External Chart)

For non-app-template charts, use `chart.spec.sourceRef` with local HelmRepository:

```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: example-charts
spec:
  interval: 2h
  url: https://charts.example.com
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: example
spec:
  interval: 1h
  chart:
    spec:
      chart: example
      version: 1.0.0
      sourceRef:
        kind: HelmRepository
        name: example-charts
  values:
    # Chart-specific values
```

#### pvc.yaml

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/v1.30.3-standalone-strict/persistentvolumeclaim-v1.json
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: example-app  # Primary PVC matches app name
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 5Gi
  storageClassName: ceph-block
```

Storage types:

| Type            | Access | Strategy      | Use Case           |
|-----------------|--------|---------------|--------------------|
| ceph-block      | RWO    | Recreate      | Config, databases  |
| ceph-filesystem | RWX    | RollingUpdate | Shared data        |
| NFS             | RWX    | RollingUpdate | Media, large files |

#### externalsecret.yaml

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/external-secrets.io/externalsecret_v1.json
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: example-app
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: infisical
  target:
    name: example-app-secret  # Kubernetes secret name
    creationPolicy: Owner
  data:
  - secretKey: API_KEY  # Key in Kubernetes secret (app's expected format)
    remoteRef:
      key: /namespace/example-app/api-key  # Infisical path (kebab-case)
```

Path format: `/namespace/app-name/secret-name`

Add secrets: `just infisical add-secret /namespace/app-name/secret-name "value"`

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

For apps with multiple processes (like Immich):

```yaml
controllers:
  main-app:
    containers:
      main:
        image: ...
  worker:
    containers:
      main:
        image: ...
  redis:
    containers:
      main:
        image: ...

service:
  main-app:
    controller: main-app
    ports:
      http:
        port: 8080
  worker:
    controller: worker
    ports:
      http:
        port: 9000
  redis:
    controller: redis
    ports:
      http:
        port: 6379

persistence:
  data:
    advancedMounts:
      main-app:
        main:
        - path: /data
      worker:
        main:
        - path: /data
```

### Intel GPU (DRA)

For apps requiring Intel GPU:

```yaml
# In ks.yaml dependsOn:
dependsOn:
- name: intel-gpu-resource-driver
  namespace: kube-system

# In helmrelease.yaml:
controllers:
  app:
    pod:
      nodeSelector:
        feature.node.kubernetes.io/custom-intel-gpu: "true"
      resourceClaims:
      - name: gpu
        resourceClaimTemplateName: app-name
    containers:
      main:
        resources:
          claims:
          - name: gpu

# Separate ResourceClaimTemplate in helmrelease.yaml values:
resourceClaimTemplates:
  app-name:
    spec:
      devices:
        requests:
        - name: gpu
          deviceClassName: gpu.intel.com
```

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
