# Claude Directives

## Critical Operational Rules

BEFORE ANY WORK: CHECK MANDATORY DEBUGGING CHECKLIST in Quality Assurance section.

### Git and GitOps Protocol

- NEVER run git commit or git push without explicit user request
- GitOps requires user commits, not Claude
- STOP after file changes and wait for user to commit/push
- This is a Flux GitOps repository - NEVER run kubectl apply, kubectl create, kubectl patch, or any
  direct Kubernetes modification commands
- All changes MUST go through GitOps workflow
- Flux manages all deployments automatically
- NEVER attempt to reconcile, apply, or sync changes after making modifications
- STOP immediately after file changes and ASK user to commit/push

### Manual Operations Decision Tree

When considering manual cluster operations:

1. GitOps solution exists → REQUIRED: Use GitOps workflow exclusively
2. One-time diagnostic operation needed → REQUIRED: Explain proposal and ASK for approval before
   execution
3. NEVER ACCEPTABLE: kubectl apply, kubectl create, kubectl patch, kubectl port-forward
4. Reconcile needed → Follow Flux reconcile strategy in Reference Sections

### kubectl Operation Restrictions

- NEVER use kubectl port-forward under ANY circumstances
- Alternatives: kubectl exec, debug pods, service exposure via HTTPRoute
- NEVER use kubectl apply, kubectl create, kubectl patch
- Diagnostic operations: kubectl get, kubectl describe, kubectl logs (approval recommended)

### Quality Assurance

MANDATORY validation sequence after ALL changes:

1. pre-commit run --all-files (or pre-commit run --files file1 file2...)
2. MUST NOT proceed to commit without completing pre-commit validation
3. Additional validation: kustomize build, kubectl dry-run, flux check

### Task Command Priority

- ALWAYS check Taskfile.yaml before using raw CLI commands
- Use task commands over direct CLI when available
- Common tasks: task reconcile, task --list

### Reference Format

- Use file.yaml:123 format when referencing code locations

### Configuration Philosophy

- PREFER YAML defaults by omission over explicit configuration
- Minimal configuration improves maintainability and clarity

### Domain References

- NEVER reference real homelab domain names in documentation or config examples
- Use domain.com for documentation examples
- Use ${SECRET_DOMAIN} in YAML manifests for actual domain references

### YAML Standards

- ALWAYS include appropriate # yaml-language-server: directive at top of YAML files
- Use URLs consistent with existing repo patterns
- Flux schemas for Flux resources
- Kubernetes JSON schemas for core K8s resources
- schemastore.org for standard files
- NEVER unnecessarily quote YAML values unless required to disambiguate or force types

### Documentation Requirements

MANDATORY documentation for non-standard configurations:

- WHY special approach was needed (chart limitations, upstream issues)
- WHAT alternatives were considered and rejected
- HOW solution works technically
- WHEN to reconsider the approach
- Place comments directly above or within relevant configuration sections
- Required for: postRenderers, kustomize patches, workarounds, deviations from defaults, custom
  resources

### Cluster Hostname Standards

- NEVER end cluster hostnames with svc.cluster.local
- ALWAYS use shortest resolvable form: service.namespace

### Authelia SecurityPolicy ReferenceGrant

When creating SecurityPolicy resources referencing Authelia:

- MUST update ReferenceGrant at kubernetes/apps/default/authelia/referencegrant.yaml
- MUST add SecurityPolicy's namespace to ReferenceGrant
- ReferenceGrant does NOT support wildcards
- Each namespace MUST be explicitly listed
- Without ReferenceGrant update: backend ref not permitted by any ReferenceGrant error

## Repository Conventions

CRITICAL: ALWAYS check existing applications before making changes. ALWAYS follow THIS repository's
established patterns. NEVER invent new patterns. NEVER adopt conventions from other repositories.

### Directory Structure

- Pattern: kubernetes/apps/namespace/app/
- Namespace directories MUST match actual namespace names exactly
- Standard files in app directory:
  - helmrelease.yaml
  - ks.yaml
  - kustomization.yaml
  - pvc.yaml
  - externalsecret.yaml
  - httproute.yaml (for non-app-template charts or dedicated routing)
  - securitypolicy.yaml (for Authelia-protected apps)
- Asset subdirectories (only when needed):
  - config/ (application configurations, may include vector configs)
  - resources/ (additional resource manifests)
  - icons/ (application icons for dashboards)
- NEVER create unnecessary subdirectories
- Co-locate all manifests in app directory unless assets require organization

### Namespace Patterns

App-to-namespace mapping (reference for Claude):

- cert-manager: cert-manager
- default: authelia, bookstack, filerun, homepage, immich, silverbullet
- dns-private: adguard-home, adguard-home-sync, dns-gateway, external-dns, secret
- external: opensprinkler
- flux-system: flux-instance, flux-operator
- home: esphome, home-assistant, zwave-js-ui
- kube-system: cilium, cloudnative-pg, coredns, external-secrets, intel-gpu-plugin,
  mariadb-operator, metrics-server, multus, node-feature-discovery, reloader, snapshot-controller,
  spegel
- media: bazarr, imagemaid, jellyseerr, kometa, plex, prowlarr, qbittorrent, radarr, radarr-4k,
  radarr-anime, recyclarr, sabnzbd, sonarr, sonarr-anime, tautulli
- network: cloudflare-dns, cloudflare-tunnel, envoy-gateway
- observability: gatus, grafana, victoria-logs-single, victoria-metrics-k8s-stack, vmrules
- rook-ceph: cluster, operator
- storage: kopia, volsync

### Kustomization Patterns

App ks.yaml file (Flux Kustomization):

- NEVER specify metadata.namespace (VIOLATION)
- MUST have spec.targetNamespace: namespace (REQUIRED)
- MUST include sourceRef with GitRepository flux-system in flux-system namespace
- Pattern example (kubernetes/apps/default/silverbullet/ks.yaml:1):

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app silverbullet
spec:
  targetNamespace: default
  path: ./kubernetes/apps/default/silverbullet
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
```

Parent kustomization.yaml file (Kustomize):

- Sets namespace: namespace at top for organization
- Lists all app ks.yaml files in resources
- Includes components (common, drift-detection)
- Pattern example (kubernetes/apps/default/kustomization.yaml:1):

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: default
components:
- ../../components/common
- ../../components/drift-detection
resources:
- ./authelia/ks.yaml
- ./bookstack/ks.yaml
- ./silverbullet/ks.yaml
```

App kustomization.yaml file:

- NEVER specify namespace field (conflicts with inheritance)
- Lists resources: helmrelease.yaml, pvc.yaml, externalsecret.yaml, etc
- May include components (volsync)
- May define configMapGenerator for app configurations
- Pattern example (kubernetes/apps/default/bookstack/kustomization.yaml:1):

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
components:
- ../../../components/volsync
resources:
- helmrelease.yaml
- mariadb.yaml
- pvc.yaml
- externalsecret.yaml
```

Kustomization logic:

- Single ks.yaml: Same namespace, timing, and lifecycle
- Multiple ks.yaml: Different namespaces, timing, lifecycle, or operator+instance patterns

### HelmRelease Patterns

Chart reference:

- ALWAYS use chartRef (NEVER chart.spec.sourceRef)
- chartRef references OCIRepository by name
- NO namespace needed in chartRef when OCIRepository is in same namespace
- Pattern example (kubernetes/apps/media/plex/helmrelease.yaml:9):

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: plex
spec:
  chartRef:
    kind: OCIRepository
    name: app-template
```

OCIRepository pattern:

- Each app owns its ocirepository.yaml file (NOT centralized)
- Located in app directory alongside helmrelease.yaml
- App-template OCIRepository is in components/common/repos/app-template/
- Referenced by all app-template applications via common component
- Non-app-template charts: Create app-specific OCIRepository
- Pattern example (kubernetes/apps/observability/victoria-logs-single/ocirepository.yaml:1):

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: victoria-logs-single
spec:
  interval: 15m
  layerSelector:
    mediaType: application.vnd.cncf.helm.chart.content.v1.tar+gzip
    operation: copy
  ref:
    tag: 0.11.16
  url: oci://ghcr.io/victoriametrics/helm-charts/victoria-logs-single
```

App-template conventions:

- HTTPRoute over Ingress for routing
- Route priority: Use route: blocks in app-template values
- Use standalone HTTPRoute only for non-app-template charts or when charts lack routing
- Add postBuild.substituteFrom: cluster-secrets for cluster-wide variables
- Service naming: Multiple services auto-prefixed with release name
- Service naming pattern: ${.Release.Name}-${service-identifier}
- Example: HelmRelease immich with service redis creates service immich-redis.default
- Route backendRefs: Use full service name (e.g., authelia-app), not identifier (e.g., app)

App naming convention:

- NEVER use cluster-apps- prefix in service/app names
- Use straightforward naming matching directory structure
- Example: mariadb-operator (NOT cluster-apps-mariadb-operator)

### Namespace Declaration Patterns

CRITICAL VIOLATIONS - Check FIRST before analysis:

- App ks.yaml: NEVER metadata.namespace (VIOLATION), MUST spec.targetNamespace: namespace (REQUIRED)
- PVCs: Inherit namespace implicitly (NO explicit namespace field)
- Parent kustomization.yaml: Sets namespace: namespace for organization only
- App kustomization.yaml: NEVER specify namespace field (inheritance conflicts)

PVC pattern example (kubernetes/apps/default/bookstack/pvc.yaml:1):

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: bookstack
  # No namespace field - inherits from parent kustomization
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: ceph-block
```

### Secret Management Patterns

ExternalSecret pattern (REQUIRED):

- NO secret.sops.yaml files (obsolete pattern)
- ALL secrets use ExternalSecret with Infisical ClusterSecretStore
- Path structure: /namespace/app/secret-name
- Naming: kebab-case for secret names and folders
- Pattern example (kubernetes/apps/default/bookstack/externalsecret.yaml:1):

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: bookstack-secret
spec:
  refreshInterval: 5m
  secretStoreRef:
    kind: ClusterSecretStore
    name: infisical
  target:
    name: bookstack-secret
    creationPolicy: Owner
  data:
  - secretKey: APP_KEY
    remoteRef:
      key: /default/bookstack/app-key
```

Secret integration priority:

1. envFrom at app level for application secrets
2. env.valueFrom for individual values
3. HelmRelease valuesFrom for chart values
4. NEVER postBuild.substituteFrom for app secrets (timing issues with ExternalSecret)
5. ONLY use postBuild.substituteFrom for: cluster-secrets, email-secrets (pre-existing)

SOPS usage (cluster-wide secrets only):

- Cluster secrets: kubernetes/components/common/sops/cluster-secrets.sops.yaml
- Email secrets: kubernetes/components/common/sops/email-secrets.sops.yaml
- SOPS commands:
  - Set: `sops set file.sops.yaml '["stringData"]["KEY"]' '"value"' --idempotent`
  - Remove: `sops unset file.sops.yaml '["stringData"]["KEY"]'`

### Storage and Mounting Patterns

CRITICAL: ReadWriteOnce (RWO) volumes REQUIRE strategy: Recreate

Deployment strategy requirements:

- RWO volumes: MUST use strategy: Recreate (RollingUpdate causes ContainerCreating failures)
- RWX/emptyDir/configMap: RollingUpdate acceptable
- Stateless apps: Prefer RollingUpdate (zero-downtime)
- Stateful apps: Use Recreate (data consistency)

Volume mounting strategy:

- globalMounts: Mounts to ALL controllers and containers (use ONLY for RWX/ConfigMaps)
- advancedMounts: Mounts to specific controller/container (REQUIRED for RWO volumes)
- Single-controller apps: advancedMounts preferred for clarity
- Multi-controller apps: NEVER globalMounts with RWO volumes

Storage class selection:

- ceph-block (RWO): Single pod exclusive, requires strategy: Recreate, use advancedMounts
- ceph-filesystem (RWX): Multi-pod sharing, RollingUpdate compatible, use globalMounts
- NFS (RWX): Multi-pod sharing for large media, RollingUpdate compatible, use globalMounts
- emptyDir: Always multi-pod compatible, use globalMounts

Pattern example (kubernetes/apps/default/authelia/helmrelease.yaml:26):

```yaml
controllers:
  authelia:
    strategy: Recreate  # Required for RWO volume

persistence:
  config:
    existingClaim: authelia
    advancedMounts:  # Required for RWO volume
      authelia:
        app:
        - path: /config
```

PVC strategy:

- volsync component: Handles backups only, does NOT create PVCs
- Manual PVC: ALL apps require explicit PVC definitions in pvc.yaml
- HelmRelease: Reference via existingClaim: appname
- File organization: ALWAYS include ./pvc.yaml in kustomization.yaml resources
- Naming: Primary PVC matches app name, additional PVCs use {app}-{purpose}

### ConfigMap Patterns

Stable naming (disableNameSuffixHash: true):

- ONLY use for cross-resource name dependencies
- Required for: Helm valuesFrom references, app-template persistence.name references
- Examples requiring stable names:
  - homepage: valuesFrom references configMap
  - cloudflare-tunnel: persistence.name references configMap
  - authelia: valuesFrom references configMap
  - grafana: persistence.name references configMap
- Pattern example (kubernetes/apps/default/homepage/kustomization.yaml:8):

```yaml
configMapGenerator:
- name: homepage-config
  files:
  - ./config/settings.yaml
  - ./config/services.yaml
  options:
    disableNameSuffixHash: true
```

Reloader annotation:

- ALWAYS use reloader.stakater.com/auto: "true" for ALL apps
- NEVER use specific secret/configmap reload annotations
- Annotation placement: HelmRelease spec.values.controllers.{controller}.annotations
- Pattern example:

```yaml
controllers:
  app:
    annotations:
      reloader.stakater.com/auto: "true"
```

### Component Usage Patterns

common component:

- Included in ALL namespace parent kustomization.yaml files
- Provides: app-template OCIRepository, SOPS secrets (cluster-secrets, email-secrets), namespace
  resource
- Located at: kubernetes/components/common/
- Pattern: - ../../components/common in components list

drift-detection component:

- Included in ALL namespace parent kustomization.yaml files
- Provides: Drift detection for Flux resources
- Located at: kubernetes/components/drift-detection/
- Pattern: - ../../components/drift-detection in components list

volsync component:

- Included in app kustomization.yaml when backup needed
- Provides: Kopia-based backup with S3 backend to s3://volsync-backups/{APP}/
- Located at: kubernetes/components/volsync/
- REQUIRES postBuild.substitute.APP variable in app ks.yaml
- Optional: postBuild.substitute.VOLSYNC_PVC to override PVC name (defaults to ${APP})
- REQUIRES postBuild.substituteFrom: cluster-secrets for S3 credentials
- Pattern example (kubernetes/apps/default/silverbullet/ks.yaml:22):

```yaml
postBuild:
  substitute:
    APP: silverbullet
    VOLSYNC_PVC: silverbullet-data
  substituteFrom:
  - kind: Secret
    name: cluster-secrets
```

### Security Patterns

SecurityPolicy for Authelia:

- MUST follow canonical example: kubernetes/apps/media/radarr/securitypolicy.yaml:1
- CRITICAL headers requirements:
  - headersToExtAuth: accept, cookie, authorization, x-forwarded-proto
  - headersToBackend: remote-user, remote-groups, remote-email, remote-name, set-cookie
- NEVER use wildcards for headers (ALWAYS explicit headers)
- backendRef: authelia-app service in default namespace port 9091
- Path: /api/authz/ext-authz/
- backendSettings.retry.numRetries: 3
- MUST update ReferenceGrant at kubernetes/apps/default/authelia/referencegrant.yaml
- NO explicit namespace in metadata (inherits from parent kustomization)
- Pattern example (kubernetes/apps/media/radarr/securitypolicy.yaml:1):

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: SecurityPolicy
metadata:
  name: radarr-auth
spec:
  targetRefs:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: radarr
  extAuth:
    headersToExtAuth:
    - accept
    - cookie
    - authorization
    - x-forwarded-proto
    http:
      backendRef:
        name: authelia-app
        namespace: default
        port: 9091
      path: /api/authz/ext-authz/
      headersToBackend:
      - remote-user
      - remote-groups
      - remote-email
      - remote-name
      - set-cookie
      backendSettings:
        retry:
          numRetries: 3
```

Container security context:

- ALWAYS use rootless containers
- Standard security context:

```yaml
securityContext:
  runAsUser: 1000
  runAsGroup: 1000
  runAsNonRoot: true
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: [ALL]
```

Pod security context:

```yaml
securityContext:
  fsGroup: 1000
  fsGroupChangePolicy: OnRootMismatch
```

### Native Sidecar Pattern for Jobs

CRITICAL for Jobs/CronJobs with RWO volumes:

- Jobs/CronJobs using ReadWriteOnce PVCs MUST use native sidecar pattern
- Pattern: initContainers with restartPolicy: Always
- Purpose: Auto-terminates sidecar after main container completes
- Without this: Sidecar keeps running, preventing RWO volume release, causing Multi-Attach errors on
  next run
- Pattern example (kubernetes/apps/media/kometa/helmrelease.yaml:1):

```yaml
controllers:
  kometa:
    type: cronjob
    initContainers:
      vector-sidecar:
        image:
          repository: timberio/vector
          tag: 0.50.0-alpine
        restartPolicy: Always  # Native sidecar - auto-terminates
```

Standard deployments:

- Use regular sidecar containers (NOT initContainers)
- No special restartPolicy needed

## Namespace Management

CRITICAL NAMESPACE RULES - MANDATORY ENFORCEMENT:

App ks.yaml files:

- NEVER specify metadata.namespace (VIOLATION)
- MUST have explicit spec.targetNamespace: namespace (REQUIRED)

PVC files:

- Inherit namespace implicitly
- NO explicit namespace field (VIOLATION if present)

Parent kustomization.yaml:

- Sets namespace: namespace only for organization
- NO patches needed for namespace propagation

App kustomization.yaml:

- NEVER specify namespace field (inheritance conflicts)

Pattern example (kubernetes/apps/default/silverbullet/ks.yaml:1):

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app silverbullet
spec:
  targetNamespace: default
  path: ./kubernetes/apps/default/silverbullet
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
```

Debugging protocol for namespace issues:

1. Check ALL namespace violations above before other analysis
2. Compare broken app against known working app (silverbullet, plex)
3. Look for metadata.namespace violations in ks.yaml files
4. Verify app has explicit spec.targetNamespace declaration
5. Verify PVCs inherit namespace implicitly (no explicit namespace)
6. NEVER suggest architectural changes until basic violations ruled out

## Reference Sections

### Deployment Standards

GitRepository sourceRef pattern:

- ALWAYS use flux-system as name
- MUST include namespace: flux-system in sourceRef
- Verify sourceRef matches existing Kustomizations
- Pattern:

```yaml
sourceRef:
  kind: GitRepository
  name: flux-system
  namespace: flux-system
```

SOPS decryption:

- MUST include secretRef: {name: sops-age} for encrypted secrets
- Required in Flux Kustomization spec for SOPS-encrypted files
- Pattern:

```yaml
spec:
  decryption:
    provider: sops
    secretRef:
      name: sops-age
```

HTTPRoute pattern:

- HTTPRoute over Ingress for all routing
- Route through existing gateways (internal, external)
- Gateway references in parentRefs
- Pattern:

```yaml
route:
  app:
    hostnames:
    - app.${SECRET_DOMAIN}
    parentRefs:
    - name: external
      namespace: network
      sectionName: https
```

Health probes:

- NEVER use executable commands in probes
- Use httpGet, tcpSocket, or grpc probe types only

Timing:

- NEVER specify explicit timeouts/intervals without specific issue justification
- Use Flux defaults unless problem documented

Validation sequence:

1. pre-commit run --all-files (or --files for specific files)
2. kustomize build (optional validation)
3. kubectl dry-run (optional validation)
4. flux check (optional validation)

Helm operations:

- Template rendering: helm template releasename chartpath -f values.yaml
- Chart search: helm search repo chartname --versions
- Values inspection: helm show values chartrepo/chartname
- NEVER proceed to commit without pre-commit validation

### Container Image Standards

Primary choice (ALWAYS prefer):

- ghcr.io/home-operations/* containers
- Mission: Semantically versioned, rootless, multi-architecture
- Philosophy: KISS principle, one process per container, NO s6-overlay, Alpine/Ubuntu base
- Run as non-root user (65534:65534 default)
- Fully Kubernetes security compatible
- Examples: ghcr.io/home-operations/sabnzbd, ghcr.io/home-operations/plex
- Verification: <https://github.com/home-operations/containers/tree/main/apps/>

Secondary choice (only if home-operations unavailable):

- ghcr.io/onedr0p/* containers
- Legacy containers moved to home-operations
- Still maintained but home-operations preferred

Avoid:

- ghcr.io/hotio/* and containers using s6-overlay, gosu, unconventional initialization
- Compatibility issues with Kubernetes security contexts

Tag immutability:

- NEVER use latest or rolling tags without SHA256 digests
- PREFER semantic versions with SHA256: app:4.5.3@sha256:8053...
- ACCEPTABLE semantic versions without SHA256: app:4.5.3 (renovatebot adds digest)
- REQUIRED SHA256 pinning for production workloads

Security context configuration:

```yaml
securityContext:
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 65534
  fsGroupChangePolicy: OnRootMismatch
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: [ALL]
```

Volume standards:

- Config volume: ALWAYS /config (hardcoded in home-operations containers)
- Temp storage: emptyDir to /tmp when readOnlyRootFilesystem enabled
- CLI options: Use args: field in container spec

Signature verification:

```bash
gh attestation verify --repo home-operations/containers \
  oci://ghcr.io/home-operations/${APP}:${TAG}
```

### Network Configuration

HTTPRoute requirements:

- HTTPRoute ONLY (never Ingress)
- Route through existing gateways
- Use app-template route: blocks for app-template applications
- Standalone HTTPRoute for non-app-template charts or when charts lack routing

LoadBalancer restrictions:

- NEVER create LoadBalancer without explicit user discussion
- Cilium IPAM for static assignment: lbipam.cilium.io/ips annotation
- Internal gateway: 192.168.50.72
- External gateway: 192.168.50.73
- Application LoadBalancers: 192.168.50.100+ (direct pod access, bypassing gateways)

External-DNS configuration:

- Configure target annotations on Gateways ONLY
- NEVER configure on HTTPRoutes
- Use gateway-httproute source for CNAME inheritance
- Pattern:

```yaml
metadata:
  annotations:
    external-dns.alpha.kubernetes.io/target: external.${SECRET_DOMAIN}
```

Health probes:

- NEVER use executable commands
- Use httpGet, tcpSocket, or grpc only

Hostnames:

- Use shortest resolvable form
- Pattern: service.namespace (NOT service.namespace.svc.cluster.local)

### Secret Management Reference

Infisical ClusterSecretStore:

```yaml
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: infisical
spec:
  provider:
    infisical:
      hostAPI: https://app.infisical.com
      auth:
        universalAuthCredentials:
          clientId:
            key: CLIENT_ID
            name: infisical-credentials
            namespace: kube-system
          clientSecret:
            key: CLIENT_SECRET
            name: infisical-credentials
            namespace: kube-system
      secretsScope:
        projectSlug: home-ops
        environmentSlug: prod
        secretsPath: /
        recursive: false
        expandSecretReferences: false
```

ExternalSecret usage:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: app-secret
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: infisical
  target:
    name: app-secret
    creationPolicy: Owner
  data:
  - secretKey: API_KEY
    remoteRef:
      key: /default/app/api-key
```

Infisical CLI operations:

```bash
# List secrets
infisical secrets --env=prod --path=/namespace/app

# Get secret
infisical secrets get NAME --env=prod --path=/namespace/app

# Set secret (supports multiple)
infisical secrets set NAME=value NAME2=value2 --env=prod --path=/namespace/app

# Delete secret
infisical secrets delete NAME --env=prod --path=/namespace/app

# List folders
infisical secrets folders get --env=prod --path=/namespace

# Create folder
infisical secrets folders create --name app-name --path=/namespace --env=prod
```

CRITICAL: Create folders BEFORE setting secrets. Setting secrets in non-existent folders fails
silently (exit 0) without creating secrets.

Conventions:

- kebab-case for names and folders
- Path structure: /namespace/app/secret-name

### Storage and Backup Reference

NFS patterns:

- Static PVs for existing data
- PVCs in app directories
- subPath mounting for directory isolation

Database isolation:

- NEVER share databases between apps
- Deploy dedicated database instances per app
- Use CloudNativePG for PostgreSQL
- Use MariaDB Operator for MariaDB

PVC strategy:

- volsync component: Backups only, does NOT create PVCs
- Manual PVC: ALL apps require explicit pvc.yaml
- HelmRelease: existingClaim: appname
- File organization: Include ./pvc.yaml in kustomization.yaml
- Naming: Primary matches app name, additional use {app}-{purpose}

S3 Object Storage (Garage):

- Endpoint: <http://192.168.1.58:3900>
- Region: garage
- Credentials: kubernetes/components/common/sops/cluster-secrets.sops.yaml
- Buckets: postgres-backups, volsync-backups, bookstack-backups
- Access pattern: postBuild.substituteFrom: cluster-secrets for ${S3_ENDPOINT}, ${S3_ACCESS_KEY_ID},
  ${S3_SECRET_ACCESS_KEY}

AWS CLI usage:

```bash
eval $(sops -d kubernetes/components/common/sops/cluster-secrets.sops.yaml \
  | yq eval '.stringData | to_entries | .[] | select(.key | startswith("S3_")) \
  | "export " + .key + "=" + .value' -)
aws --endpoint-url=$S3_ENDPOINT --region=$S3_REGION s3 ls
```

VolSync backup:

- Component location: kubernetes/components/volsync/
- Data mover: Kopia with S3 backend
- Destination: s3://volsync-backups/{APP}/
- Features: Hourly backups, 24h/7d retention, zstd-fastest, non-root (1000:1000), 5Gi cache
- Validation: kubectl get replicationsources -A, rclone ls garage:volsync-backups/

CloudNativePG backup:

- PostgreSQL only
- Barman with WAL archiving to s3://postgres-backups/{cluster}/
- PITR support, automated retention, compression
- Status: kubectl get scheduledbackup -A, kubectl describe cluster name | rg -i backup

### Vector Logging Standards

Standard fields (ALWAYS use):

- message: Log content (required)
- timestamp: Event time (required)
- level: Log level (debug, info, warning, error, critical)
- severity: Severity class (optional)
- host, source_type: Standard metadata
- NEVER create custom equivalents

Vector sidecar pattern:

Standard deployments/statefulsets:

```yaml
containers:
  app: {}
  vector-sidecar:
    image:
      repository: timberio/vector
      tag: 0.50.0-alpine
```

Jobs/CronJobs with RWO volumes (REQUIRED native sidecar):

```yaml
initContainers:
  vector-sidecar:
    image:
      repository: timberio/vector
      tag: 0.50.0-alpine
    restartPolicy: Always  # Auto-terminates after main container
```

Vector configuration:

- Separate VRL file: NEVER inline source in vector.yaml
- ALWAYS use file: parameter for VRL programs
- VRL files typically in config/ subdirectory (e.g., config/vector.yaml)
- Test samples: ALWAYS include test data for validation
- Transform reference pattern:

```yaml
transforms:
  parse_app:
    type: remap
    inputs: [app_logs]
    file: /etc/vector/parse-app.vrl
```

Vector testing (MANDATORY before deployment):

```bash
./scripts/test-vector-config.py kubernetes/apps/namespace/app/config/parse-app.vrl
./scripts/test-vector-config.py VRL_FILE --samples test.json
```

Test sample format:

```json
[
  {"name": "test-name", "input": {"message": "log"}, "expect": {"field": "value"}},
  {"name": "blank-dropped", "input": {"message": ""}, "expect": null}
]
```

VRL regex best practices:

- Prefer non-greedy .*? over greedy .* for general best practice
- Performance impact negligible for typical log message sizes (less than 500 chars)

### Flux Operations Reference

Reconcile strategy (MANDATORY two-stage):

Stage 1 (15s timeout):

```bash
flux reconcile helmrelease NAME -n NAMESPACE --timeout 15s
```

Stage 2 (if timeout):

```bash
flux reconcile helmrelease NAME -n NAMESPACE --reset
flux reconcile helmrelease NAME -n NAMESPACE --with-source --force --timeout=5m
```

Flags explained:

- --reset: Clears retry exhaustion
- --with-source: Refreshes source
- --force: Bypasses retry limits

### Conventional Commits

MANDATORY path-based commit classification:

Direct path mapping:

- ci: .github/workflows/**, .taskfiles/**, Taskfile.yaml
- build: renovate.json5, .renovate/**
- chore: .editorconfig, .gitignore, .yamllint.yaml, .markdownlint-cli2.yaml,
  .pre-commit-config.yaml, tooling configs
- docs: *.md, docs/**, LICENSE, SECURITY.md, CODEOWNERS

Kubernetes manifests (inspect git diff):

- feat: New apps/services, new capabilities (new kubernetes/apps/namespace/app/ directories)
- fix: Bug fixes, crash loops, probe failures, resource issues, alert resolutions
- refactor: Resource reorganization, manifest restructuring, no behavior change

Scripts:

- feat: New script capabilities in scripts/
- fix: Script bug fixes, validation corrections
- chore: Script reorganization without behavior change

Breaking changes (type!:):

- API/CRD version upgrades requiring manual intervention
- Incompatible Helm chart major version upgrades
- Storage class or PVC changes requiring data migration

Scopes from paths:

- kubernetes/apps/namespace/app/** → (app)
- kubernetes/flux/** → (flux)
- talos/** → (talos)
- .github/**, .taskfiles/** → (ci)
- scripts/** → (scripts)
- .renovate/**, renovate.json5 → (deps) when modifying Renovate behavior (NOT automated dependency
  PRs)

Examples:

- fix(plex): resolve crash loop due to missing volume mount
- feat(silverbullet): add new note-taking application
- refactor(media): reorganize namespace structure
- ci: update pre-commit hooks

## Cluster and Environment Reference

### Stack Overview

- Operating System: Talos Linux
- Orchestration: Kubernetes with Flux v2 GitOps
- Secrets: SOPS with Age encryption, External Secrets Operator with Infisical
- Storage: Rook Ceph (distributed), NFS from Nezuko, Garage S3
- Automation: Taskfile, mise, talhelper
- Renovate: renohate[bot] (intentional name), config at renovate.json5, modular configs in
  .renovate/

### Essential Commands

Setup:

```bash
mise trust .mise.toml && mise install
```

Sync cluster:

```bash
task reconcile
```

Validation (see Quality Assurance section):

```bash
pre-commit run --all-files
```

List tasks:

```bash
task --list
```

GitOps flow:

1. Modify kubernetes/ manifests
2. Run validation (pre-commit)
3. User commits and pushes (NOT Claude)
4. Flux auto-applies changes
5. Optional: task reconcile for immediate sync

### Network Details

Network configuration:

- Subnet: 192.168.1.0/24
- Gateway: 192.168.1.1
- API: 192.168.1.70
- LoadBalancer IPs (Cilium IPAM):
  - .71-.99: Kubernetes infrastructure (gateways, DNS, system services)
    - DNS: 192.168.50.71
    - Internal Gateway: 192.168.50.72
    - External Gateway: 192.168.50.73
  - .100+: Application LoadBalancers (direct pod access)
    - Plex: 192.168.50.100
- Cloudflare Tunnel: 6b689c5b-81a9-468e-9019-5892b3390500 → 192.168.50.73

### Node Details

Control plane:

- lucy: 192.168.1.54 (physical)
- nami: 192.168.1.50 (NUC)
- marin: 192.168.1.59 (NUC)

Workers:

- sakura: 192.168.1.62 (NUC)
- hanekawa: 192.168.1.63 (NUC)

Storage:

- Rook Ceph: Distributed across nodes
- NFS: Nezuko 192.168.1.58 (Media 100Ti, Photos 10Ti, FileRun 5Ti)
- Garage S3: 192.168.1.58:3900

### Ceph Toolbox

Permanent toolbox deployment enabled via Helm chart values in
kubernetes/apps/rook-ceph/cluster/helmrelease.yaml.

Common commands:

```bash
# Interactive shell
kubectl exec -n rook-ceph deploy/rook-ceph-tools -it -- bash

# Cluster health
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph status

# RBD operations
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- rbd ls ceph-block
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- rbd status IMAGE -p ceph-block
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- rbd info IMAGE -p ceph-block

# RBD watchers (debugging stuck volumes)
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- rbd status IMAGE -p ceph-block

# Force unmap (emergency only - data loss risk)
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- rbd unmap -o force /dev/rbd/NUMBER
```

### DNS Architecture

AdGuard Home:

- Subnet-based filtering with VLAN client overrides
- Filtering rules:
  - Main LAN (192.168.1.0/24): Global baseline (590k+ rules)
  - Privacy VLANs (IoT/Work): Social media blocking
  - Kids VLAN: Comprehensive content restrictions
  - Guest VLAN: Adult content blocking
  - Cameras VLAN: Minimal filtering
- API: `https://dns.${SECRET_DOMAIN}/control` (credentials in dns-private-secret)

### Intel GPU for Applications

Intel GPU allocation:

- Resource request: gpu.intel.com/i915: 1
- Device Plugin: Intel Device Plugin Operator manages GPU access
- Dependencies: Apps requiring GPU must depend on intel-gpu-plugin in kube-system
- OpenVINO: Set OPENVINO_DEVICE: GPU for hardware ML acceleration
- Media: Use render device script for multi-GPU VA-API/QSV workloads

### Available Scripts

Claude-relevant scripts only:

- app-scout.sh: Kubernetes migration discovery
  - Usage: ./scripts/app-scout.sh discover APP
  - Usage: ./scripts/app-scout.sh correlate APP1 APP2
  - File inspection: Use octocode MCP tools after discovery
- bootstrap-apps.sh: Application bootstrap for cluster initialization
- test-vector-config.py: Vector VRL configuration testing
  - Usage: ./scripts/test-vector-config.py CONFIG.yaml [-v] [--samples test.json]
  - REQUIRED for Vector config changes
- validate-vmrules.sh: VMRule CRD syntax validation
  - Usage: ./scripts/validate-vmrules.sh [PATH]
- vmalert-query.py: Query vmalert API via ephemeral kubectl pods
  - Usage: ./scripts/vmalert-query.py [firing|pending|inactive|detail NAME|rules|json|history
    [DURATION]]
- ceph.sh: Ceph command wrapper via rook-ceph-tools
  - Usage: ./scripts/ceph.sh CEPH-COMMAND
- query-victorialogs.py: Query VictoriaLogs
  - Usage: ./scripts/query-victorialogs.py --app APP -n 10
  - Usage: ./scripts/query-victorialogs.py "error" --start 1h
  - Options: --detail, --level, --namespace, --pod, --container
- update-gitignore/: Modular gitignore generation
  - Usage: ./scripts/update-gitignore/update.sh
