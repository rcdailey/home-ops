# Claude Directives

## Tier 1: Breaking Rules

These rules prevent immediate cluster failures. Violations cause crashes, data corruption, or GitOps
drift.

### GitOps and Validation

- **NEVER run git commit/push without explicit user request** - GitOps requires user commits for
  accountability
- **NEVER use kubectl apply/create/patch** - Bypasses GitOps, creates configuration drift. Use
  manifest changes only.
- **NEVER proceed to commit without pre-commit validation** - Run `pre-commit run <files>` after ANY
  changes

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
- **NEVER use chart.spec.sourceRef** - Deprecated Flux pattern. Always use chartRef (references
  OCIRepository by name).
- **chartRef requires NO namespace** - When OCIRepository is in same namespace as HelmRelease
- **NEVER use executable commands in health probes** - Use httpGet, tcpSocket, or grpc only
  (security and reliability)

### Secrets and Configuration

- **NEVER use secret.sops.yaml files** - Obsolete pattern replaced by ExternalSecret with Infisical
  ClusterSecretStore
- **NEVER use postBuild.substituteFrom for app secrets** - Timing race condition with ExternalSecret
  creation causes failures
- **ONLY use postBuild.substituteFrom for**: cluster-secrets, email-secrets (pre-existing SOPS
  secrets managed centrally)
- **NEVER inline VRL source in vector.yaml** - Separate VRL file required for testing and validation
- **ALWAYS include test data for VRL validation** - Use ./scripts/test-vector-config.py for
  validation

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
- Service naming pattern: `${.Release.Name}-${service-identifier}`
- Primary: `ghcr.io/home-operations/*` containers (semantically versioned, rootless, multi-arch)
- Secondary: `ghcr.io/onedr0p/*` containers (if home-operations unavailable)
- Avoid: `ghcr.io/hotio/*` and containers using s6-overlay, gosu
- NEVER use latest, rolling, or non-semantic tags (semantic versioning required)
- SHA256 digests: Automatically added by renovatebot

### Security and Networking

- HTTPRoute ONLY for all routing (never Ingress)
- NEVER use kubectl port-forward under ANY circumstances (alternatives: kubectl exec, debug pods,
  HTTPRoute exposure)
- NEVER configure External-DNS on HTTPRoutes (Gateways only)
- NEVER create LoadBalancer without explicit user discussion
- Route backendRefs: Use full service name (e.g., authelia-app), not identifier (e.g., app)
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

## Tier 3: Reference

Implementation patterns, operational workflows, and environment details.

### Repository and File Organization

Pattern: `kubernetes/apps/namespace/app/`

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

### Kustomization and Manifest Patterns

Namespace inheritance: Parent kustomization.yaml sets namespace → Inherits to all resources
(exceptions: Flux Kustomization `spec.targetNamespace`, sourceRef cross-namespace references)

**Flux Kustomization (ks.yaml):**

- Uses `spec.targetNamespace: namespace` (NOT metadata.namespace)
- Must be listed in parent kustomization.yaml resources
- GitRepository sourceRef: ALWAYS use flux-system as name with namespace: flux-system
- SOPS decryption: MUST include secretRef: {name: sops-age} for encrypted secrets
- Single ks.yaml: Same namespace, timing, lifecycle; Multiple: Different namespaces/timing/lifecycle

**Kustomize files:**

- Parent kustomization.yaml: Sets namespace, lists app ks.yaml files, includes components (common,
  drift-detection)
- App kustomization.yaml: Lists resources (helmrelease.yaml, pvc.yaml, externalsecret.yaml), may
  include components (volsync), may define configMapGenerator

**Chart and storage patterns:**

- OCIRepository: Each app owns its ocirepository.yaml (exception: app-template in
  components/common/repos/)
- App-template: Add postBuild.substituteFrom: cluster-secrets; service naming auto-prefixed with
  release name
- PVC: Namespace inherited, volsync handles backups only, ALL apps require explicit pvc.yaml,
  reference via existingClaim
- Volume types: ceph-block (RWO/Recreate/advancedMounts), ceph-filesystem (RWX/RollingUpdate), NFS
  (RWX), emptyDir
- Mount config: RWO requires advancedMounts; RWX/emptyDir use globalMounts (multi-controller) or
  advancedMounts (single-controller)

**Secrets:**

- ExternalSecret: Infisical key /namespace/app/secret-name (kebab-case), secretKey maps to env var
  name, ClusterSecretStore infisical, creationPolicy Owner
- Priority: 1) envFrom, 2) env.valueFrom, 3) HelmRelease valuesFrom, 4) NEVER
  postBuild.substituteFrom for app secrets
- SOPS (cluster-wide only): cluster-secrets.sops.yaml, email-secrets.sops.yaml; commands: sops set /
  sops unset

**ConfigMaps and components:**

- Stable naming (disableNameSuffixHash: true): ONLY for cross-resource dependencies (Helm
  valuesFrom, persistence.name)
- Components: common (app-template OCIRepository, SOPS secrets, namespace), drift-detection (all
  namespaces)
- Volsync: Include when PVC backup needed; postBuild.substitute.APP, postBuild.substituteFrom:
  cluster-secrets; s3://volsync-backups/{APP}/

**Security and container patterns:**

- Authelia SecurityPolicy: kubernetes/apps/media/radarr/securitypolicy.yaml:1; headers:
  headersToExtAuth (accept, cookie, authorization, x-forwarded-proto), headersToBackend
  (remote-user, remote-groups, remote-email, remote-name, set-cookie); backendRef: authelia-app port
  9091
- Native sidecar for Jobs: initContainers with restartPolicy: Always (see Tier 1)
- Container config: /config volume, emptyDir to /tmp, args: field for CLI options

### Operational Workflows

**GitOps flow:** Modify manifests → Run pre-commit → User commits/pushes → Flux auto-applies →
Optional task reconcile

**Commands:**

- Setup: mise trust .mise.toml && mise install
- Sync cluster: task reconcile
- Validation: pre-commit run --all-files (or --files for specific files)
- Flux reconcile helmrelease: `flux reconcile hr NAME -n NAMESPACE --force` (`--reset` clears retry,
  `--with-source` refreshes source)
- Helm: helm template releasename chartpath -f values.yaml
- Talos: `task talos:apply-node IP=192.168.1.X` to apply configuration. Only do this one node at a
  time!

**Secret management (Infisical):**

- ClusterSecretStore: hostAPI <https://app.infisical.com>, auth: universalAuthCredentials, scope:
  projectSlug home-ops, environmentSlug prod
- CLI: infisical secrets [list|get NAME|set NAME=value|delete NAME] --env=prod
  --path=/namespace/app
- CRITICAL: Create folders BEFORE setting secrets (fails silently otherwise)
- Folder creation: infisical secrets folders create --name=folder-name --path=/parent/path
  --env=prod
- Path structure: /namespace/app/secret-name, kebab-case naming

**Conventional commits (MANDATORY path-based):**

- ci: `.github/workflows/**`, `.taskfiles/**`, Taskfile.yaml
- build: renovate.json5, `.renovate/**`
- chore: .editorconfig, .gitignore, .yamllint.yaml, .markdownlint-cli2.yaml, .pre-commit-config.yaml
- docs: `*.md`, `docs/**`, LICENSE, SECURITY.md, CODEOWNERS
- feat (k8s): New apps/services (new kubernetes/apps/namespace/app/ directories)
- fix (k8s): Bug fixes, crash loops, probe failures, resource issues, alert resolutions
- refactor (k8s): Resource reorganization, no behavior change
- feat/fix (scripts): Script capabilities/bug fixes
- Breaking (type!:): API/CRD upgrades, incompatible Helm upgrades, storage migrations
- Examples: fix(plex): resolve crash loop, feat(silverbullet): add note-taking app

### Environment and Infrastructure

**Stack components:**

- OS: Talos Linux
- Orchestration: Kubernetes with Flux v2 GitOps
- Secrets: SOPS with Age encryption, External Secrets Operator with Infisical
- Storage: Rook Ceph (distributed), NFS from Nezuko, Garage S3
- Automation: Taskfile, mise, talhelper
- Renovate: `renohate[bot]` (intentional name)

**Network topology:**

- Main subnet: 192.168.1.0/24
- BGP subnet (Cilium LoadBalancers): 192.168.50.0/24
- Gateway (Unifi UDMP): 192.168.1.1
- Kubernetes API: 192.168.1.70
- LoadBalancer IPs (Cilium IPAM): 192.168.50.71-.99 (infrastructure), 192.168.50.100+ (applications)
- Cloudflare Tunnel: 6b689c5b-81a9-468e-9019-5892b3390500

**Cluster nodes:**

- Control plane: lucy (192.168.1.54), nami (192.168.1.50), marin (192.168.1.59)
- Workers: sakura (192.168.1.62), hanekawa (192.168.1.63)

**Storage backends:**

- Rook Ceph: Distributed block/filesystem storage across cluster nodes
- NFS (Nezuko 192.168.1.58): Media (100Ti), Photos (10Ti), FileRun (5Ti)
- Garage S3 (192.168.1.58:3900): Region garage, buckets: postgres-backups, volsync-backups,
  bookstack-backups
- CloudNativePG: Barman WAL archiving to s3://postgres-backups/{cluster}/
- Ceph toolbox: kubectl exec -n rook-ceph deploy/rook-ceph-tools -- [ceph status | rbd COMMAND]

**Intel GPU support:**

- Resource request: gpu.intel.com/i915: 1
- Management: Intel Device Plugin Operator
- Dependencies: Apps requiring GPU must depend on intel-gpu-plugin in kube-system
- OpenVINO: Set OPENVINO_DEVICE: GPU for hardware acceleration

**Available namespaces:**

Namespace followed by a list of apps in that namespace:

- cert-manager: cert-manager
- default: authelia, bookstack, filerun, homepage, immich, silverbullet
- dns-private: adguard-home, adguard-home-sync, dns-gateway, external-dns
- external: opensprinkler
- flux-system: flux-instance, flux-operator
- home: esphome, home-assistant, zwave-js-ui
- kube-system: cilium, cloudnative-pg, coredns, external-secrets, intel-gpu-plugin,
  mariadb-operator, metrics-server, multus, node-feature-discovery, reloader, snapshot-controller,
  spegel, descheduler
- media: bazarr, imagemaid, jellyseerr, kometa, plex, prowlarr, qbittorrent, radarr, radarr-4k,
  radarr-anime, recyclarr, sabnzbd, sonarr, sonarr-anime, tautulli
- network: cloudflare-dns, cloudflare-tunnel, envoy-gateway
- observability: gatus, grafana, victoria-logs-single, victoria-metrics-k8s-stack, vmrules
- rook-ceph: cluster, operator
- storage: kopia, volsync

**Utility scripts:**

- app-scout.sh: Kubernetes migration discovery
- test-vector-config.py: Vector VRL configuration testing (REQUIRED for Vector changes)
- validate-vmrules.sh: VMRule CRD syntax validation
- vmalert-query.py: Query vmalert API via ephemeral kubectl pods
- ceph.sh: Ceph command wrapper via rook-ceph-tools
- query-victorialogs.py: Query VictoriaLogs
- update-gitignore/: Modular gitignore generation
- query-container-metrics.py: Get historical VictoriaMetrics data for containers
