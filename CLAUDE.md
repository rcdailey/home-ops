# Claude Directives

## Critical Operational Rules

**BEFORE ANY DEBUGGING OR ANALYSIS - CHECK THE MANDATORY DEBUGGING CHECKLIST IN QUALITY ASSURANCE
SECTION**

**IMPORTANT:** Claude MUST:

- **GitOps Protocol**: This is a Flux GitOps repository. NEVER run `kubectl apply -f` commands. Flux
  manages all deployments. NEVER attempt to reconcile, apply, or sync changes after making
  modifications. STOP immediately after file changes and ASK user to commit/push changes.
- **Git Protocol**: NEVER run `git commit`/`git push` without explicit user request. GitOps requires
  user commits, not Claude. STOP after changes and wait for user to commit/push.
- **No Direct Kubernetes Operations**: NEVER use `kubectl apply`, `kubectl create`, `kubectl patch`,
  or any direct Kubernetes modification commands. All changes must go through GitOps workflow.
- **Task Priority**: Use `task` commands over CLI. Check `Taskfile.yaml` first.
- **Reference Format**: Use `file.yaml:123` format when referencing code.
- **Configuration**: Favor YAML defaults over explicit values for cleaner manifests.
- **Domain References**: NEVER reference real homelab domain names in documentation or config files.
  Use `domain.com` for examples or `${SECRET_DOMAIN}` in YAML manifests.
- **YAML Language Server**: ALWAYS include appropriate `# yaml-language-server:` directive at top of
  YAML files using URLs consistent with existing repo patterns. Use Flux schemas for Flux resources,
  Kubernetes JSON schemas for core K8s resources, and schemastore.org for standard files.
- **MANDATORY Documentation for Special Configurations**: When implementing workarounds, patches, or
  non-standard configurations, ALWAYS add comprehensive comments explaining:
  - WHY the special approach was needed (chart limitations, upstream issues, etc.)
  - WHAT alternatives were considered and why they were rejected
  - HOW the solution works technically (postRenderers, patches, custom resources)
  - WHEN to reconsider the approach (upstream fixes, better alternatives)
  - Examples requiring documentation: postRenderers, kustomize patches, deviations from defaults,
    custom resources instead of Helm values, workarounds for limitations
  - Place comments directly above or within relevant configuration sections
  - These comments are ESSENTIAL for future maintenance and decision-making
- NEVER end cluster hostnames with `svc.cluster.local`; only use `<service>.<namespace>`.
- **Authelia SecurityPolicy ReferenceGrant**: When creating SecurityPolicy resources that reference
  Authelia's external auth service (`authelia` in `default` namespace), you MUST update the
  ReferenceGrant at `kubernetes/apps/default/authelia/referencegrant.yaml` to include the
  SecurityPolicy's namespace. ReferenceGrant does NOT support wildcards - each namespace must be
  explicitly listed. Without this, the SecurityPolicy will fail with "backend ref not permitted by
  any ReferenceGrant" error.

## Namespace Management Strategy

**CRITICAL NAMESPACE PATTERNS - MANDATORY ENFORCEMENT:**

This repository uses an **Explicit Namespace Declaration** pattern that differs from onedr0p's
inheritance-based approach for enhanced reliability in GitOps operations.

### Core Philosophy Comparison

**onedr0p/home-ops Pattern** (dual namespace declaration):

```yaml
# App ks.yaml example from onedr0p
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app home-assistant
  namespace: &namespace default  # Declares metadata.namespace
spec:
  targetNamespace: *namespace     # Also declares targetNamespace
```

- App ks.yaml files HAVE `metadata.namespace` with YAML anchors
- Also uses `targetNamespace: *namespace` for consistency
- Parent kustomization sets `namespace: <namespace>`
- PVCs inherit namespace implicitly (no explicit declarations)
- Relies on Kustomize namespace propagation for resources

**This Repository Pattern** (explicit-declaration):

- Parent kustomization sets `namespace: <namespace>` for organization
- App ks.yaml files NEVER have `metadata.namespace` (VIOLATION)
- Each app Kustomization explicitly declares `spec.targetNamespace: <namespace>`
- PVCs inherit namespace implicitly (no explicit declarations)
- Self-contained apps with clear namespace declarations

### Mandatory Namespace Requirements

**CRITICAL VIOLATIONS - Claude MUST check FIRST before analysis:**

- **App ks.yaml Files**: NEVER specify `metadata.namespace` (VIOLATION - remove immediately)
- **App ks.yaml Files**: MUST have explicit `spec.targetNamespace: <namespace>` (REQUIRED)
- **PVC Files**: Inherit namespace implicitly (no explicit namespace declarations)
- **Parent Kustomization**: Sets `namespace: <namespace>` only (no patches needed)
- **App Kustomization**: NEVER specify `namespace` field (inheritance conflicts)

### Pattern Examples

**CORRECT App Kustomization** (`kubernetes/apps/media/plex/ks.yaml`):

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: plex
spec:
  targetNamespace: media  # REQUIRED: Explicit declaration
  interval: 1h
  # ... rest of spec
```

**CORRECT PVC Declaration** (`kubernetes/apps/default/bookstack/pvc.yaml`):

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: bookstack
  # No namespace field - inherits from parent kustomization
spec:
  accessModes:
  - ReadWriteOnce
  # ... rest of spec
```

**CORRECT Parent Kustomization** (`kubernetes/apps/default/kustomization.yaml`):

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: default  # Organization only
resources:
- ./bookstack/ks.yaml
- ./silverbullet/ks.yaml
```

### Debugging Protocol for Namespace Issues

When ANY namespace-related error occurs, Claude MUST immediately:

1. Check ALL namespace violations above before any other analysis
2. Compare broken app against known working app (e.g., silverbullet)
3. Look for `metadata.namespace` violations in ks.yaml files
4. Verify app has explicit `spec.targetNamespace` declaration
5. Verify PVCs inherit namespace implicitly (no explicit namespace fields)
6. NEVER suggest architectural changes until basic violations are ruled out

### Why This Pattern

- **Reliability**: Deterministic namespace resolution with explicit targetNamespace
- **Clarity**: Self-contained apps with clear namespace targets
- **Debugging**: Easier tracing of namespace-related issues
- **Consistency**: Prevents timing issues during resource creation/backups

## Quality Assurance & Validation

### Mandatory Debugging Checklist

Claude MUST check FIRST before analysis:

- Apply complete namespace requirements from "Namespace Management Strategy"
- Use debug pods for introspection (NOT `kubectl port-forward`)
- All solutions MUST be GitOps/configuration-based (NO adhoc cluster fixes)
- Start debugging with `kubectl get events -n <namespace>`

### Essential Validation Sequence

Claude MUST run ALL steps after changes:

1. **Flux Testing**: `./scripts/flux-local-test.sh`
2. **Pre-commit Checks**: `pre-commit run --all-files` (or `pre-commit run --files <files>`)
3. **Additional Validation**: kustomize build → kubectl dry-run → flux check

### Required Tools

- **Helm**: `helm template`, `helm search repo <chart> --versions`, `helm show values` for secrets
- **MUST NOT proceed to commit without completing flux-local-test.sh and pre-commit validation**

## Container Image Standards

### Critical Container Image Priority

- **Primary Choice**: `ghcr.io/home-operations/*` - ALWAYS prefer home-operations containers when
  available
  - Mission: Provide semantically versioned, rootless, multi-architecture containers
  - Philosophy: KISS principle, one process per container, no s6-overlay, Alpine/Ubuntu base
  - Run as non-root user (65534:65534 by default), fully Kubernetes security compatible
  - Examples: `ghcr.io/home-operations/sabnzbd`, `ghcr.io/home-operations/qbittorrent`
- **Secondary Choice**: `ghcr.io/onedr0p/*` - Use only if home-operations doesn't provide the
  container
  - Legacy containers that have moved to home-operations organization
  - Still maintained but home-operations is preferred for new deployments
- **Avoid**: `ghcr.io/hotio/*` and containers using s6-overlay, gosu, or unconventional
  initialization
  - These often have compatibility issues with Kubernetes security contexts
  - Prefer home-operations containers which eschew such tools by design

### Mandatory Image Standards & Verification

1. **Image Selection Process:**
   - **Always check** `https://github.com/home-operations/containers/tree/main/apps/` first
   - Only contribute/use if: upstream actively maintained AND (no official image OR no multi-arch OR
     uses s6-overlay/gosu)
   - Check for deprecation notices (6-month removal timeline)

2. **Tag Immutability Requirements:**
   - **NEVER** use `latest` or `rolling` tags without SHA256 digests
   - **PREFER** semantic versions with SHA256: `app:4.5.3@sha256:8053...`
   - **ACCEPTABLE** semantic versions without SHA256: `app:4.5.3` (renovatebot will add digest)
   - **REQUIRED** SHA256 pinning for production workloads ensures true immutability

3. **Security Context Configuration:**

   ```yaml
   securityContext:
     runAsUser: 1000          # Customizable
     runAsGroup: 1000         # Customizable
     fsGroup: 65534
     fsGroupChangePolicy: OnRootMismatch
     allowPrivilegeEscalation: false
     readOnlyRootFilesystem: true  # Requires emptyDir mounts for /tmp
     capabilities:
       drop: [ALL]
   ```

4. **Volume Standards:**
   - Config volume: ALWAYS `/config` (hardcoded)
   - Temp storage: emptyDir to `/tmp` for readOnlyRootFilesystem
   - CLI options: Use `args:` field

5. **Signature Verification:** `gh attestation verify --repo home-operations/containers
   oci://ghcr.io/home-operations/${APP}:${TAG}`

## Deployment Standards

### Critical Flux Patterns

- **GitRepository**: ALWAYS use `flux-system` name, verify sourceRef matches existing Kustomizations
- **CRITICAL**: GitRepository sourceRef MUST include `namespace: flux-system`
- **CRITICAL**: SOPS decryption MUST include `secretRef: {name: sops-age}` - this is required for
  encrypted secrets
- **OCIRepository over HelmRepository**: ALWAYS prefer OCIRepository when available. Verify OCI
  support via Context7/official docs before migration. HelmRepository is legacy - only use when
  upstream lacks OCI. Reference: `docs/memory-bank/helmrepository-to-ocirepository-migration.md`
- **OCIRepository Pattern**: Each app owns its `ocirepository.yaml` (NOT centralized). Use
  `chartRef` (not `chart.spec.sourceRef`): `chartRef: {kind: OCIRepository, name: app-name}`. No
  namespace needed in chartRef (same namespace). Structure: `ocirepository.yaml` with
  `layerSelector`, `ref.tag`, `url: oci://registry/path/chart-name`. Example: rook-ceph,
  victoria-metrics-k8s-stack
- **App-Template**: HTTPRoute over Ingress, add `postBuild.substituteFrom: cluster-secrets`
- **App-Template Service Naming**: Services auto-prefixed with release name when multiple services
  exist. Pattern: `{{ .Release.Name }}-{{ service-identifier }}`. Example: HelmRelease `immich` with
  service identifier `redis` creates service `immich-redis.default`. DNS references use full
  prefixed name.
- **Route backendRefs**: When using explicit `route.*.rules.backendRefs.name`, use full service name
  (e.g., `authelia-app`), not identifier (e.g., `app`). Without explicit rules, app-template
  auto-resolves service names.
- **Directory Structure**: `kubernetes/apps/<namespace>/<app>/` - namespace dirs MUST match names
  exactly
- **File Organization**: All manifests co-located (helmrelease.yaml, ks.yaml, kustomization.yaml,
  secrets, pvcs). Subdirectories only for assets (config/, resources/, icons/)
- **Kustomization Logic**: Single ks.yaml for same namespace+timing+lifecycle. Multiple for
  different namespaces/timing/lifecycle or operator+instance patterns
- **Explicit Namespace Pattern**: See "Namespace Management Strategy" section for complete
  requirements
- **Naming Convention**: NEVER use `cluster-apps-` prefix in service/app names. Use straightforward
  naming that matches the directory structure (e.g., `mariadb-operator`, not
  `cluster-apps-mariadb-operator`)
- **Validation**: See "Quality Assurance & Validation" section above
- **Helm**: See "Quality Assurance & Validation" section above
- **Timing**: Never specify explicit timeouts/intervals without specific issue justification

## Storage & Secrets

### Important Patterns

- **NFS**: Static PVs for existing data, PVCs in app dirs, subPath mounting
- **Database Isolation**: NEVER share databases between apps, deploy dedicated instances
- **Secret Integration Priority**: 1) `envFrom` at app, 2) `env.valueFrom`, 3) HelmRelease
  `valuesFrom`. NEVER `postBuild.substituteFrom` for app secrets (timing issues with ExternalSecret)
- **ONLY use `postBuild.substituteFrom`**: cluster-secrets, email-secrets (pre-existing secrets)
- **Secret Management**: App-isolated secrets, `sops --set` for changes, `sops unset` for removal
- **Chart Analysis**: See "Quality Assurance & Validation" section above for verification methods

### Infisical ESO Integration

- **Provider**: Native ESO Infisical provider with Universal Auth (Machine Identity)
- **Implementation**: Standard External Secrets Operator with Infisical backend
- **Pattern**: Use ClusterSecretStore + ExternalSecret resources - no custom CRDs
- **Organization**: Path-based secrets using `/namespace/app/secret-name` structure

#### Infisical ClusterSecretStore

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/external-secrets.io/clustersecretstore_v1.json
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

#### ExternalSecret Usage

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/external-secrets.io/externalsecret_v1.json
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

#### Infisical CLI Usage

**Common Operations:**

```bash
infisical secrets --env=prod --path=/namespace/app              # List
infisical secrets get <name> --env=prod --path=/namespace/app   # Get
infisical secrets set <name>=<value> --env=prod --path=/ns/app  # Set (multi supported)
infisical secrets delete <name> --env=prod --path=/ns/app       # Delete
```

**Folder Management:**

```bash
infisical secrets folders get --env=prod --path=/namespace
infisical secrets folders create --name app-name --path=/namespace --env=prod
```

**CRITICAL:** Create folders BEFORE setting secrets. Setting secrets in non-existent folders fails
silently (exit 0) without creating secrets.

**Conventions:** kebab-case for names/folders, path structure: `/namespace/app/secret-name`

### PVC Strategy

- **volsync component**: Handles backups only - does NOT create PVCs
- **Manual PVC**: All apps require explicit PVC definitions in pvc.yaml
- **HelmRelease**: `existingClaim: appname` (direct name reference)
- **File organization**: Always include `./pvc.yaml` in kustomization.yaml
- **Naming**: Primary PVC matches app name, additional PVCs use `{app}-{purpose}` pattern

## Storage & Deployment Strategy

### Critical Storage and Deployment Rules

Claude MUST enforce these patterns:

#### Deployment Strategy Requirements

**MANDATORY: ReadWriteOnce (RWO) volumes require Recreate strategy:**

- RWO + RollingUpdate = INCOMPATIBLE (ContainerCreating failures)
- RWO volumes: single pod exclusive access
- RollingUpdate starts new pod before terminating old = volume conflict
- **SOLUTION: `strategy: Recreate` with RWO volumes**

**Strategy Selection:**

- RWO volumes → `strategy: Recreate` (REQUIRED)
- RWX/emptyDir/configMap only → `strategy: RollingUpdate` (acceptable)
- Stateless apps → prefer RollingUpdate (zero-downtime)
- Stateful apps → use Recreate (data consistency)

#### Volume Mounting Strategy

**Volume Mount Rules:**

- **globalMounts**: Mounts to ALL controllers and containers - use only for RWX volumes/ConfigMaps
- **advancedMounts**: Mounts to specific controller/container - REQUIRED for RWO volumes
- **Single-controller apps**: `globalMounts` acceptable, `advancedMounts` preferred for clarity
- **Multi-controller apps**: NEVER use `globalMounts` with RWO volumes

##### Storage Class Guidelines

- **ReadWriteOnce (RWO)**: `ceph-block` - Single pod exclusive, requires `strategy: Recreate`
- **ReadWriteMany (RWX)**: `ceph-filesystem`, NFS - Multi-pod sharing, compatible with
  `RollingUpdate`
- **emptyDir/configMap**: Always multi-pod compatible

##### Storage Selection Strategy

- **App-specific data**: `ceph-block` (RWO) + `advancedMounts` + `Recreate`
- **Shared config**: ConfigMaps + `globalMounts` + any strategy
- **Multi-pod data**: `ceph-filesystem` (RWX) + `globalMounts` + `RollingUpdate`
- **Large media**: NFS PVs (RWX) + `globalMounts` + `RollingUpdate`

## ConfigMap & Reloader Strategy

### Important Notes

Use stable names (`disableNameSuffixHash: true`) ONLY for:

- Helm `valuesFrom` references (external-dns, cloudflare-dns)
- App-template `persistence.name` references (homepage, cloudflare-tunnel)
- Cross-resource name dependencies

**ALWAYS use** `reloader.stakater.com/auto: "true"` for ALL apps. NEVER use specific secret reload.

**Critical**: App-template `persistence.name` requires literal string matching - cannot resolve
Kustomize hashes.

## Network Rules

### Critical Network Patterns

- **HTTPRoute ONLY**: HTTPRoute over Ingress, route through existing gateways
- **LoadBalancer Ban**: NEVER create LoadBalancer without explicit user discussion
- **Gateway IPs**: Use externalIPs (192.168.1.72 internal, 192.168.1.73 external) not LoadBalancer
- **External-DNS**: Configure target annotations on Gateways ONLY, never HTTPRoutes. Use
  gateway-httproute source for CNAME inheritance
- **Route Priority**: Use app-template `route:` blocks for all app-template applications. Only use
  standalone HTTPRoute for non-app-template charts or when dedicated Helm charts lack routing
  capabilities
- **Health Probes**: NEVER use executable commands
- **Hostnames**: Use shortest resolvable form, avoid FQDNs when unnecessary

## Authelia App Protection

### SecurityPolicy Standards

**CRITICAL: ALL SecurityPolicy resources MUST follow the exact pattern from the canonical example.**

**Canonical Reference:** `kubernetes/apps/media/radarr/securitypolicy.yaml`

**Required Configuration Elements:**

1. **headersToExtAuth** - CRITICAL for session validation:
   - `accept` - HTTP Accept header
   - `cookie` - Sends session cookies to Authelia for validation
   - `authorization` - Authorization header for bearer tokens
   - `x-forwarded-proto` - Required for HTTPS validation
   - **Without these**: Authentication validation fails

2. **headersToBackend** - CRITICAL for session management:
   - `set-cookie` - Passes Authelia session cookies back to client
   - `remote-user`, `remote-groups`, `remote-email`, `remote-name` - User identity headers
   - **Without set-cookie**: Authentication fails
   - **NEVER use wildcards**: Always use explicit headers

3. **backendRef** - Use singular (not array `backendRefs`)
   - Backend: `authelia` service in `default` namespace, port `9091`
   - Path: `/api/authz/ext-authz/`

4. **backendSettings.retry.numRetries: 3** - Retry configuration

5. **Namespace inheritance** - NEVER specify `namespace` in metadata (inherits from parent
   kustomization)

6. **Schema URL**:
   `https://datreeio.github.io/CRDs-catalog/gateway.envoyproxy.io/securitypolicy_v1alpha1.json`

**Validation Checklist:**

- Compare against radarr/securitypolicy.yaml before committing
- Verify namespace is listed in `kubernetes/apps/default/authelia/referencegrant.yaml`
- Ensure all required headers are present (no wildcards)
- Confirm NO explicit namespace in metadata (relies on kustomization inheritance)

## Stack Overview

Talos K8s + Flux GitOps: Talos Linux, Flux v2, SOPS/Age, Rook Ceph + NFS, Taskfile, mise, talhelper.

## Essential Commands

- **Setup**: `mise trust .mise.toml && mise install`
- **Sync**: `task reconcile`
- **Validate**: See "Quality Assurance & Validation" section above
- **List Tasks**: `task --list`

**Note**: Taskfile includes for `bootstrap` and `talos` exist at `.taskfiles/bootstrap/` and
`.taskfiles/talos/`.

## GitOps Flow

1. Modify `kubernetes/` manifests
2. **VALIDATION** (See "Quality Assurance & Validation" section above)
3. **USER COMMITS/PUSHES** (not Claude)
4. Flux auto-applies
5. Optional: `task reconcile` for immediate sync

## Cluster Info

- **Network**: `192.168.1.0/24`, Gateway: `192.168.1.1`, API: `192.168.1.70`
- **Gateways**: DNS `192.168.1.71`, Internal `192.168.1.72`, External `192.168.1.73`
- **Tunnel**: `6b689c5b-81a9-468e-9019-5892b3390500` → `192.168.1.73`

### Ceph Toolbox

Permanent toolbox deployment for Ceph operations and troubleshooting at
`kubernetes/apps/rook-ceph/toolbox/`.

**Common Commands:**

```bash
# Interactive shell
kubectl exec -n rook-ceph deploy/rook-ceph-tools -it -- bash

# Check cluster health
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph status

# RBD operations
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- rbd ls ceph-block
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- rbd status <image-name> -p ceph-block
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- rbd info <image-name> -p ceph-block

# Check RBD watchers (for debugging stuck volumes)
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- rbd status <image-name> -p ceph-block

# Force unmap RBD image (emergency use only - data loss risk)
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- rbd unmap -o force /dev/rbd/<number>
```

### Nodes

- **Control Plane**:
  - rias: `192.168.1.61` (VM)
  - nami: `192.168.1.50` (NUC)
  - marin: `192.168.1.59` (NUC)
- **Workers**:
  - sakura: `192.168.1.62` (NUC)
  - hanekawa: `192.168.1.63` (NUC)

- **Storage**: Rook Ceph (distributed), NFS from Nezuko `192.168.1.58` (Media 100Ti, Photos 10Ti,
  FileRun 5Ti), Garage S3 `192.168.1.58:3900`

## Directory Structure

### Pattern

`kubernetes/apps/<namespace>/<app>/`

- **Standard Files**: helmrelease.yaml, ks.yaml, kustomization.yaml, secret.sops.yaml,
  httproute.yaml, pvc.yaml
- **Asset Subdirs**: config/, resources/, icons/ (only when needed)
- **Namespace Kustomization**: Lists all app ks.yaml files
- **Key Namespaces**: kube-system, flux-system, network, rook-ceph, storage, cert-manager, default,
  dns-private

## Intel GPU for Applications

### Important GPU Patterns

- **Resource Request**: `gpu.intel.com/i915: 1` for Intel GPU allocation via Device Plugin Operator
- **Device Plugin**: Intel Device Plugin Operator manages GPU access automatically (no
  supplementalGroups needed)
- **Dependencies**: Apps requiring GPU must depend on `intel-gpu-plugin` in `kube-system` namespace
- **OpenVINO**: Set `OPENVINO_DEVICE: GPU` for hardware ML acceleration
- **Media**: Use render device script for multi-GPU VA-API/QSV workloads

## Critical Security

- **SOPS**: Encrypted files MUST NEVER be committed unencrypted
- **External-DNS**: Auto-manages DNS for new services

## DNS Architecture

### AdGuard Home

Subnet-based filtering with VLAN client overrides for network segmentation.

#### Filtering Rules

- **Main LAN** (192.168.1.0/24): Global baseline (590k+ rules)
- **Privacy VLANs** (IoT/Work): Social media blocking
- **Kids VLAN**: Comprehensive content restrictions
- **Guest VLAN**: Adult content blocking
- **Cameras VLAN**: Minimal filtering for compatibility

#### API Access

`https://dns.${SECRET_DOMAIN}/control` (credentials in `dns-private-secret`)

## S3 Object Storage (Garage)

### Configuration

- **Endpoint**: `http://192.168.1.58:3900` (Nezuko server)
- **Region**: `garage` (custom Garage region name)
- **Access**: Cluster-level credentials stored in `cluster-secrets.sops.yaml`

### Credentials Access

Credentials are stored in
`/home/robert/code/home-ops/kubernetes/components/common/sops/cluster-secrets.sops.yaml`:

- `S3_ENDPOINT`: `http://192.168.1.58:3900`
- `S3_REGION`: `garage`
- `S3_ACCESS_KEY_ID`: Encrypted in cluster secrets
- `S3_SECRET_ACCESS_KEY`: Encrypted in cluster secrets

### AWS CLI Usage

```bash
# Extract credentials from cluster-secrets
eval $(sops -d kubernetes/components/common/sops/cluster-secrets.sops.yaml | yq eval '.stringData | to_entries | .[] | select(.key | startswith("S3_")) | "export " + .key + "=" + .value' -)

aws --endpoint-url=$S3_ENDPOINT --region=$S3_REGION s3 ls
```

### Current S3 Buckets

- **postgres-backups**: CloudNativePG database backups (immich, etc.)
- **volsync-backups**: Kopia-based application data backups via volsync
- **bookstack-backups**: Application backups
- S3-compatible API for application integration

### Application Integration

Apps can reference S3 credentials via `postBuild.substituteFrom: cluster-secrets` pattern:

```yaml
postBuild:
  substituteFrom:
  - kind: Secret
    name: cluster-secrets
```

Then use `${S3_ENDPOINT}`, `${S3_ACCESS_KEY_ID}`, etc. in manifests.

### SOPS Commands

```bash
# Set value
sops set secret.sops.yaml '["stringData"]["KEY_NAME"]' '"value"'

# Remove value
sops unset secret.sops.yaml '["stringData"]["KEY_NAME"]'
```

**Notes:** Index format `'["section"]["key"]'`, values JSON-encoded, use `--idempotent` flag

## Backup & Data Protection

### VolSync (Application Data Backups)

- **Component Location**: `kubernetes/components/volsync/`
- **Data Mover**: Kopia with S3 backend (modern, replaces rsync/rclone)
- **Destination**: `s3://volsync-backups/{APP}/` (per-app isolation)

#### Usage Pattern

```yaml
components: [../../../components/volsync]
postBuild:
  substitute:
    APP: appname  # REQUIRED
    VOLSYNC_PVC: custom-name  # Override if PVC name != app name
```

**Features:** Hourly backups, 24h/7d retention, zstd-fastest compression, non-root (1000:1000), 5Gi
cache PVC

**Validation:** `kubectl get replicationsources -A`, `rclone ls garage:volsync-backups/`

### CloudNativePG (Database Backups)

PostgreSQL only. Barman with WAL archiving to `s3://postgres-backups/{cluster}/`. PITR, automated
retention, compression.

**Status:** `kubectl get scheduledbackup -A`, `kubectl describe cluster <name> | rg -i backup`

### Component Integration Requirements

#### Critical

Apps using volsync component must provide:

1. `APP` variable via `postBuild.substitute`
2. Correct PVC name (defaults to `${APP}`, override with `VOLSYNC_PVC`)
3. S3 credentials via `postBuild.substituteFrom: cluster-secrets`

#### Common Issues

- Missing `APP` substitution → `variable not set (strict mode): "APP"`
- Wrong PVC name → `PersistentVolumeClaim "appname" not found`
- Check PVC names: `kubectl get pvc -n <namespace>`

## Log Collection Standards

### Vector Standard Fields

**ALWAYS use standard fields** (NEVER create custom equivalents):

- `message` - Log content (required)
- `timestamp` - Event time (required)
- `level` - Log level: debug, info, warning, error, critical
- `severity` - Severity class (optional)
- `host`, `source_type` - Standard metadata

### Vector Sidecar Pattern (MANDATORY)

**REQUIRED: Sidecar per app** (separation of concerns, app-owned config, isolated parsing):

**Standard Deployments/StatefulSets:**

```yaml
containers:
  app: {}
  vector-sidecar:
    image: {repository: timberio/vector, tag: 0.50.0-alpine}
```

**Jobs/CronJobs with RWO volumes:**

```yaml
initContainers:
  vector-sidecar:
    image: {repository: timberio/vector, tag: 0.50.0-alpine}
    restartPolicy: Always  # Native sidecar - auto-terminates after main container
```

**CRITICAL**: Jobs/CronJobs using ReadWriteOnce (RWO) PVCs MUST use native sidecar pattern
(`initContainers` + `restartPolicy: Always`). Without this, sidecar keeps running after job
completes, preventing RWO volume release and causing Multi-Attach errors on next run. See kometa
example.

### Vector Directory Convention (STRICT)

**MANDATORY structure**: `kubernetes/apps/<namespace>/<app>/vector/`

```txt
<app>/
├── vector/
│   ├── vector.yaml        # REQUIRED: Vector config (sources, transforms, sinks)
│   ├── parse-<app>.vrl    # REQUIRED: VRL transform program (separate file)
│   └── test-samples.json  # REQUIRED: Test data for validation
```

**Critical requirements**:

1. **Separate VRL file**: NEVER use inline `source:` in vector.yaml. ALWAYS use `file:` parameter
2. **Naming convention**: VRL file MUST be named `parse-<appname>.vrl`
3. **Test data**: ALWAYS include `test-samples.json` with representative log samples
4. **Transform reference**: Use `file: /etc/vector/parse-<app>.vrl` in vector.yaml

**Example vector.yaml**:

```yaml
transforms:
  parse_app:
    type: remap
    inputs: [app_logs]
    file: /etc/vector/parse-app.vrl  # NOT inline source
```

**Example kustomization.yaml**:

```yaml
configMapGenerator:
- name: app-vector-configmap
  files:
  - vector.yaml=./vector/vector.yaml
  - parse-app.vrl=./vector/parse-app.vrl
```

### Vector Configuration Testing (MANDATORY)

**REQUIRED: Test before deployment:**

```bash
./scripts/test-vector-config.py kubernetes/apps/<ns>/<app>/vector/parse-<app>.vrl
./scripts/test-vector-config.py <vrl-file> --samples <test.json>  # Explicit samples
```

**Test sample format** (`test-samples.json`):

```json
[
  {"name": "test-name", "input": {"message": "log"}, "expect": {"field": "value"}},
  {"name": "blank-dropped", "input": {"message": ""}, "expect": null}
]
```

Script auto-discovers `test-samples.json` in VRL directory. **ALWAYS run before committing Vector
changes.**

### VRL Regex Best Practices

**Regex quantifiers**: Prefer non-greedy `.*?` over greedy `.*` for general best practice, though
performance impact is negligible with typical log message sizes (< 500 chars). IDE warnings about
`.*` performance are technically valid but overly cautious for log parsing use cases.

## Available Scripts

Only scripts relevant for AI usage is below; do not use the `annotate-yaml.py` or `validate-yaml.py`
scripts.

- **app-scout.sh**: Kubernetes migration discovery tool
  - Usage: `./scripts/app-scout.sh discover <app-name>` for deployment pattern discovery
  - Usage: `./scripts/app-scout.sh correlate <app1> <app2>` for multi-app pattern analysis
  - **File Inspection**: After discovery, use octocode MCP tools (githubViewRepoStructure,
    githubSearchCode, githubGetFileContent) to retrieve configuration files from discovered
    repositories
- **bootstrap-apps.sh**: Application bootstrap for cluster initialization
- **flux-local-test.sh**: **ESSENTIAL VALIDATION**
  - Usage: `./scripts/flux-local-test.sh`
  - **REQUIRED** in validation sequence (see "Quality Assurance & Validation" section)
- **test-vector-config.py**: Vector VRL configuration testing
  - Usage: `./scripts/test-vector-config.py <config.yaml> [-v] [--samples <test.json>]`
  - **REQUIRED** for Vector config changes (fail-fast validation)
- **validate-vmrules.sh**: VMRule CRD syntax validation using vmalert dry-run
  - Usage: `./scripts/validate-vmrules.sh [path-to-vmrules-directory]`
- **vmalert-query.py**: Query vmalert API for alert/rule inspection via ephemeral kubectl pods
  - Usage: `./scripts/vmalert-query.py [firing|pending|inactive|detail <name>|rules|json]`
- **ceph.sh**: Ceph command convenience wrapper via rook-ceph-tools pod
  - Usage: `./scripts/ceph.sh <ceph-command>` (e.g., `./scripts/ceph.sh status`)
- **update-gitignore/**: Modular gitignore generation system
  - Usage: `./scripts/update-gitignore/update.sh`
  - Combines custom patterns from `custom/` with gitignore.io templates
