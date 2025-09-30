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

**Reliability**: Explicit targetNamespace declarations provide deterministic namespace resolution
**Clarity**: App kustomizations are self-contained with clear namespace targets **Debugging**:
Easier to trace namespace-related issues with explicit app declarations **Consistency**: Prevents
timing issues during resource creation and backup operations

## Quality Assurance & Validation

**MANDATORY DEBUGGING CHECKLIST - Claude MUST check FIRST before analysis:**

- Apply complete namespace requirements from "Namespace Management Strategy" section above
- Never do `kubectl port-forward`; run debug pods instead for introspection
- Never do adhoc fixes against the cluster; all solutions MUST be gitops/configuration-based

**ESSENTIAL VALIDATION SEQUENCE - Claude MUST run ALL steps after changes:**

1. **Flux Testing**: `./scripts/flux-local-test.sh`
2. **Pre-commit Checks**: `pre-commit run --all-files` (or `pre-commit run --files <files>`)
3. **Additional Validation**: kustomize build → kubectl dry-run (server) → flux check

**REQUIRED TOOLS FOR VERIFICATION:**

- **Helm Validation**: `helm template <release> <chart>` and `helm search repo <chart> --versions`
- **Chart Analysis**: `helm show values <chart>/<name> --version <version>` for secret integration
- **Configuration Testing**: `./scripts/test-renovate.sh` for renovate config validation
- **Debug Analysis**: You MUST start with `kubectl get events -n namespace` when performing cluster
  debugging or analysis.

**Claude MUST NOT proceed to user commit without completing flux-local-test.sh and pre-commit
validation.**

## Container Image Standards

**CRITICAL CONTAINER IMAGE PRIORITY:**

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

**MANDATORY IMAGE STANDARDS & VERIFICATION:**

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
   # REQUIRED Kubernetes security context for home-operations images
   securityContext:
     runAsUser: 1000          # Can be customized
     runAsGroup: 1000         # Can be customized
     fsGroup: 65534           # Requires CSI support
     fsGroupChangePolicy: OnRootMismatch
     allowPrivilegeEscalation: false
     readOnlyRootFilesystem: true  # May require additional emptyDir mounts
     capabilities:
       drop: [ALL]
   ```

4. **Volume Standards:**
   - **Configuration volume**: ALWAYS `/config` (hardcoded, non-configurable)
   - **Temporary storage**: Mount emptyDir volumes to `/tmp` for readOnlyRootFilesystem
   - **Command arguments**: Use Kubernetes `args:` field for CLI-only configuration options

5. **Image Signature Verification:**

   ```bash
   # Verify GitHub CI build provenance
   gh attestation verify --repo home-operations/containers oci://ghcr.io/home-operations/${APP}:${TAG}
   ```

## Deployment Standards

**CRITICAL FLUX PATTERNS:**

- **GitRepository**: ALWAYS use `flux-system` name, verify sourceRef matches existing Kustomizations
- **CRITICAL**: GitRepository sourceRef MUST include `namespace: flux-system`
- **CRITICAL**: SOPS decryption MUST include `secretRef: {name: sops-age}` - this is required for
  encrypted secrets
- **App-Template**: Use bjw-s OCIRepository with `chartRef: {kind: OCIRepository, name:
  app-template}`, HTTPRoute over Ingress, add `postBuild.substituteFrom: cluster-secrets`
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

**IMPORTANT PATTERNS:**

- **NFS**: Static PVs for existing data, PVCs in app dirs, subPath mounting
- **Database Isolation**: NEVER share databases between apps, deploy dedicated instances
- **Secret Integration Priority**: 1) `envFrom` at app, 2) `env.valueFrom`, 3) HelmRelease
  `valuesFrom`. NEVER `postBuild.substituteFrom` for app secrets (timing issues with ExternalSecret)
- **ONLY use `postBuild.substituteFrom`**: cluster-secrets, email-secrets (pre-existing secrets)
- **Secret Management**: App-isolated secrets, `sops --set` for changes, `sops unset` for removal
- **Chart Analysis**: See "Quality Assurance & Validation" section above for verification methods

**INFISICAL ESO INTEGRATION:**

- **Provider**: Native ESO Infisical provider with Universal Auth (Machine Identity)
- **Implementation**: Standard External Secrets Operator with Infisical backend
- **Pattern**: Use ClusterSecretStore + ExternalSecret resources - no custom CRDs
- **Organization**: Path-based secrets using `/namespace/app/secret-name` structure

**INFISICAL CLUSTERSECRETSTORE:**

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

**EXTERNALSECRET USAGE:**

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

**INFISICAL CLI USAGE:**

**Common Operations:**

```bash
# List secrets in path
infisical secrets --env=prod --path=/namespace/app

# Get specific secret(s)
infisical secrets get secret-name --env=prod --path=/namespace/app

# Set secrets (supports multiple)
infisical secrets set secret-name=value --env=prod --path=/namespace/app
infisical secrets set api-key=value db-password=secret --env=prod --path=/namespace/app

# Delete secret
infisical secrets delete secret-name --env=prod --path=/namespace/app
```

**Folder Management:**

```bash
# List folders in path
infisical secrets folders get --env=prod --path=/namespace

# Create folder (REQUIRED before setting secrets)
infisical secrets folders create --name app-name --path=/namespace --env=prod
```

**CRITICAL:** Folders MUST be created BEFORE setting secrets. Setting secrets in non-existent
folders fails silently (exit code 0) without creating secrets. Always create folder structure first.

**Conventions:**

- **Secret names:** kebab-case (e.g., `secret-key`, `postgres-password`, `api-token`)
- **Folder names:** kebab-case (e.g., `default`, `media`, `silverbullet`, `radarr-4k`)
- **Path structure:** `/namespace/app/secret-name` (hierarchical organization by namespace/app)

**PVC STRATEGY:**

- **volsync component**: Handles backups only - does NOT create PVCs
- **Manual PVC**: All apps require explicit PVC definitions in pvc.yaml
- **HelmRelease**: `existingClaim: appname` (direct name reference)
- **File organization**: Always include `./pvc.yaml` in kustomization.yaml
- **Naming**: Primary PVC matches app name, additional PVCs use `{app}-{purpose}` pattern

## Storage & Deployment Strategy

**CRITICAL STORAGE AND DEPLOYMENT RULES - Claude MUST enforce these patterns:**

### Deployment Strategy Requirements

**MANDATORY: ReadWriteOnce volumes require Recreate strategy:**

- **ReadWriteOnce (RWO) + RollingUpdate = INCOMPATIBLE** - causes ContainerCreating failures
- **RWO volumes can only be mounted by ONE pod at a time**
- **RollingUpdate starts new pod before terminating old pod = volume conflict**
- **SOLUTION: Always use `strategy: Recreate` with RWO volumes**

```yaml
# CORRECT: Recreate strategy with RWO volumes
controllers:
  app:
    strategy: Recreate    # REQUIRED for RWO volumes
    containers:
      main:
        # app config
persistence:
  config:
    type: persistentVolumeClaim
    existingClaim: app-config-pvc  # RWO volume
    advancedMounts:
      app:
        main:
        - path: /config

# WRONG: RollingUpdate with RWO volumes causes stuck pods
controllers:
  app:
    strategy: RollingUpdate  # FAILS with RWO volumes
```

**Strategy Selection Rules:**

- **Apps with RWO volumes**: ALWAYS use `strategy: Recreate`
- **Apps with only RWX/emptyDir/configMap volumes**: Can use `strategy: RollingUpdate`
- **Stateless apps**: Prefer `RollingUpdate` for zero-downtime updates
- **Stateful apps with persistent data**: Use `Recreate` to ensure data consistency

### Volume Mounting Strategy

**Volume Mount Rules:**

- **globalMounts**: Mounts to ALL controllers and containers - use only for RWX volumes/ConfigMaps
- **advancedMounts**: Mounts to specific controller/container - REQUIRED for RWO volumes
- **Single-controller apps**: `globalMounts` acceptable, `advancedMounts` preferred for clarity
- **Multi-controller apps**: NEVER use `globalMounts` with RWO volumes

**Storage Class Guidelines:**

- **ReadWriteOnce (RWO)**: `ceph-block` - Single pod exclusive, requires `strategy: Recreate`
- **ReadWriteMany (RWX)**: `ceph-filesystem`, NFS - Multi-pod sharing, compatible with
  `RollingUpdate`
- **emptyDir/configMap**: Always multi-pod compatible

**Volume Mount Patterns:**

```yaml
# CORRECT: RWO volume with advancedMounts + Recreate strategy
controllers:
  app:
    strategy: Recreate
persistence:
  data:
    type: persistentVolumeClaim
    existingClaim: app-data-pvc  # RWO
    advancedMounts:
      app:
        main:
        - path: /data

# CORRECT: RWX volume with globalMounts + RollingUpdate
controllers:
  app:
    strategy: RollingUpdate
persistence:
  shared:
    type: persistentVolumeClaim
    existingClaim: shared-data-pvc  # RWX
    globalMounts:
    - path: /shared

# WRONG: RWO volume with globalMounts causes Multi-Attach errors
persistence:
  data:
    type: persistentVolumeClaim
    existingClaim: app-data-pvc  # RWO
    globalMounts:  # WRONG - will fail in multi-controller apps
    - path: /data
```

**Storage Selection Strategy:**

- **App-specific persistent data**: `ceph-block` (RWO) + `advancedMounts` + `strategy: Recreate`
- **Shared configuration**: ConfigMaps + `globalMounts` + any strategy
- **Multi-pod shared data**: `ceph-filesystem` (RWX) + `globalMounts` + `RollingUpdate`
- **Large media/file storage**: NFS PVs (RWX) + `globalMounts` + `RollingUpdate`

## ConfigMap & Reloader Strategy

**IMPORTANT:** Use stable names (`disableNameSuffixHash: true`) ONLY for:

- Helm `valuesFrom` references (external-dns, cloudflare-dns)
- App-template `persistence.name` references (homepage, cloudflare-tunnel)
- Cross-resource name dependencies

**ALWAYS use** `reloader.stakater.com/auto: "true"` for ALL apps. NEVER use specific secret reload.

**Critical**: App-template `persistence.name` requires literal string matching - cannot resolve
Kustomize hashes.

## Network Rules

**CRITICAL NETWORK PATTERNS:**

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

## Authentik App Protection

**REQUIRED COMPONENTS (4 items for protected apps):**

- Proxy provider blueprint (external_host, internal_host, mode: forward_single)
- Application blueprint (links provider to app catalog)
- Provider entry in `blueprints/outpost-configuration.yaml` providers list
- SecurityPolicy targeting HTTPRoute (backend: ak-outpost-authentik-embedded-outpost, path:
  /outpost.goauthentik.io/auth/envoy)

**SETUP WORKFLOW:**

1. Create provider blueprint: external/internal hosts, intercept_header_auth: true
2. Create application blueprint: references provider by name
3. Add provider to outpost-configuration.yaml providers list
4. Create SecurityPolicy targeting app's HTTPRoute name
5. Deploy app with standard app-template route blocks

**API PROTECTION:**

- **skip_path_regex: ^/api/.*$** excludes API endpoints from auth (use appropriate API path for the
  app)
- **Required for**: Mobile clients, webhooks, API integrations
- **Alternative**: Separate HTTPRoute for API paths

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

**Nodes**:

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

**Pattern**: `kubernetes/apps/<namespace>/<app>/`

- **Standard Files**: helmrelease.yaml, ks.yaml, kustomization.yaml, secret.sops.yaml,
  httproute.yaml, pvc.yaml
- **Asset Subdirs**: config/, resources/, icons/ (only when needed)
- **Namespace Kustomization**: Lists all app ks.yaml files
- **Key Namespaces**: kube-system, flux-system, network, rook-ceph, storage, cert-manager, default,
  dns-private

## Intel GPU for Applications

**IMPORTANT GPU PATTERNS:**

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

**AdGuard Home**: Subnet-based filtering with VLAN client overrides for network segmentation.

**Network Rules**:

- **Main LAN** (192.168.1.0/24): Global baseline (590k+ rules)
- **Privacy VLANs** (IoT/Work): Social media blocking
- **Kids VLAN**: Comprehensive content restrictions
- **Guest VLAN**: Adult content blocking
- **Cameras VLAN**: Minimal filtering for compatibility

**API Access**: `https://dns.${SECRET_DOMAIN}/control` (credentials in `dns-private-secret`)

## S3 Object Storage (Garage)

**Endpoint**: `http://192.168.1.58:3900` (Nezuko server) **Region**: `garage` (custom Garage region
name) **Access**: Cluster-level credentials stored in `cluster-secrets.sops.yaml`

### S3 Credentials Access

Credentials are stored in
`/home/robert/code/home-ops/kubernetes/components/common/sops/cluster-secrets.sops.yaml`:

- `S3_ENDPOINT`: `http://192.168.1.58:3900`
- `S3_REGION`: `garage`
- `S3_ACCESS_KEY_ID`: Encrypted in cluster secrets
- `S3_SECRET_ACCESS_KEY`: Encrypted in cluster secrets

### AWS CLI Usage

```bash
# Extract credentials
eval $(sops -d kubernetes/components/common/sops/cluster-secrets.sops.yaml | yq eval '.stringData | to_entries | .[] | select(.key | startswith("S3_")) | "export " + .key + "=" + .value' -)

# Use AWS CLI with Garage
aws --endpoint-url=$S3_ENDPOINT --region=$S3_REGION s3 ls

# Alternative direct usage
AWS_ACCESS_KEY_ID=<key> AWS_SECRET_ACCESS_KEY=<secret> AWS_DEFAULT_REGION=garage aws --endpoint-url=http://192.168.1.58:3900 s3 ls
```

### Current S3 Buckets

- **postgres-backups**: CloudNativePG database backups (immich, etc.)
- **volsync-backups**: Kopia-based application data backups via volsync
- **bookstack-backups**: Legacy application backups
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

#### Set values in encrypted files

```bash
# Syntax: sops set file index value
sops set secret.sops.yaml '["stringData"]["KEY_NAME"]' '"value"'

# Examples:
sops set secret.sops.yaml '["stringData"]["API_KEY"]' '"abc123"'
sops set secret.sops.yaml '["stringData"]["WIREGUARD_PRIVATE_KEY"]' '"wOEI9rqq..."'
```

#### Remove values from encrypted files

```bash
# Syntax: sops unset file index
sops unset secret.sops.yaml '["stringData"]["KEY_NAME"]'

# Examples:
sops unset secret.sops.yaml '["stringData"]["MULLVAD_ACCOUNT"]'
sops unset secret.sops.yaml '["stringData"]["OLD_API_KEY"]'
```

#### Key points

- Index format: `'["section"]["key"]'` for YAML files
- Values must be JSON-encoded strings
- Always use single quotes around index path
- Use `--idempotent` flag to avoid errors if key exists/doesn't exist

## Backup & Data Protection

### VolSync (Application Data Backups)

- **Component Location**: `kubernetes/components/volsync/`
- **Data Mover**: Kopia with S3 backend (modern, replaces rsync/rclone)
- **Destination**: `s3://volsync-backups/{APP}/` (per-app isolation)

**Usage Pattern**:

```yaml
# In app kustomization.yaml
components:
- ../../../components/volsync
postBuild:
  substitute:
    APP: appname  # REQUIRED for component substitution
    VOLSYNC_PVC: custom-pvc-name  # Override if PVC name != app name
```

**Key Features**:

- **Scheduling**: Hourly backups (`0 * * * *`)
- **Retention**: 24 hourly, 7 daily snapshots
- **Compression**: zstd-fastest for speed/size balance
- **Security**: Runs as non-root (1000:1000), snapshot-based for consistency
- **Cache**: Dedicated 5Gi cache PVC per app for performance

**Validation Commands**:

```bash
kubectl get replicationsources -A              # Check backup sources
kubectl describe replicationsource <app> -n <ns>  # Detailed status
rclone ls garage:volsync-backups/              # Verify S3 contents
```

### CloudNativePG (Database Backups)

- **Scope**: PostgreSQL clusters only
- **Method**: Barman with continuous WAL archiving
- **Destination**: `s3://postgres-backups/{cluster}/`
- **Features**: Point-in-time recovery, automated retention, compression

**Status Check**:

```bash
kubectl get scheduledbackup -A                 # Backup schedules
kubectl describe cluster <name> | grep -i backup  # Cluster backup status
```

### Component Integration Requirements

**CRITICAL**: Apps using volsync component must provide:

1. `APP` variable via `postBuild.substitute`
2. Correct PVC name (defaults to `${APP}`, override with `VOLSYNC_PVC`)
3. S3 credentials via `postBuild.substituteFrom: cluster-secrets`

**Common Issues**:

- Missing `APP` substitution → `variable not set (strict mode): "APP"`
- Wrong PVC name → `PersistentVolumeClaim "appname" not found`
- Check PVC names: `kubectl get pvc -n <namespace>`

## Available Scripts

Only scripts relevant for AI usage is below; do not use the `annotate-yaml.py` or `validate-yaml.py`
scripts.

- **app-scout.sh**: Kubernetes migration discovery tool
- **bootstrap-apps.sh**: Application bootstrap for cluster initialization
- **flux-local-test.sh**: **ESSENTIAL VALIDATION**
  - Usage: `./scripts/flux-local-test.sh`
  - **REQUIRED** in validation sequence (see "Quality Assurance & Validation" section)
- **test-renovate.sh**: Test renovate configuration with debug output
  - Usage: `./scripts/test-renovate.sh`
  - Shows actual PR titles and validates renovate config locally
- **update-gitignore/**: Modular gitignore generation system
  - Usage: `./scripts/update-gitignore/update.sh`
  - Combines custom patterns from `custom/` with gitignore.io templates
