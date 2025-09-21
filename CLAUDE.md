# Claude Directives

## Critical Operational Rules

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

## Quality Assurance & Validation

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
- **Namespace Inheritance**: Use parent kustomization's `namespace` field and patches for automatic
  inheritance
  - Parent: `kubernetes/apps/<namespace>/kustomization.yaml` sets `namespace: <namespace>`
  - Parent: MUST include patch to add `spec.targetNamespace` to all child Kustomization resources:

    ```yaml
    patches:
    - target:
        kind: Kustomization
        group: kustomize.toolkit.fluxcd.io
      patch: |
        - op: add
          path: /spec/targetNamespace
          value: <namespace>
    ```

  - **CRITICAL**: Children individual app ks.yaml files NEVER specify `metadata.namespace` or
    `spec.targetNamespace`
  - **CRITICAL**: Kustomize kustomization.yaml files NEVER specify `namespace` field
  - Semantics: Parent's `namespace` field sets `metadata.namespace`, patch adds
    `spec.targetNamespace`
  - Result: App kustomizations live in correct namespace and deploy resources to same namespace
    automatically
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
  `valuesFrom`, 4) `postBuild.substituteFrom` (last resort)
- **Secret Management**: App-isolated secrets, `sops --set` for changes, `sops unset` for removal
- **Chart Analysis**: See "Quality Assurance & Validation" section above for verification methods

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

### Current Usage

- **immich-backups** bucket: Database backups from immich
- Used for application backups and object storage needs
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
