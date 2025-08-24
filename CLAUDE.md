# Claude Directives

## Critical Operational Rules

**IMPORTANT:** Claude MUST:

- **Git Protocol**: NEVER run `git commit`/`git push` without explicit user request. GitOps requires
  user commits, not Claude. STOP after changes and wait for user to commit/push.
- **Task Priority**: Use `task` commands over CLI. Check `Taskfile.yaml` first.
- **Reference Format**: Use `file.yaml:123` format when referencing code.
- **Configuration**: Favor YAML defaults over explicit values for cleaner manifests.
- **Domain References**: NEVER reference real homelab domain names in documentation or config files.
  Use `domain.com` for examples or `${SECRET_DOMAIN}` in YAML manifests.
- **YAML Language Server**: ALWAYS include appropriate `# yaml-language-server:` directive at top of
  YAML files using URLs consistent with existing repo patterns. Use Flux schemas for Flux resources,
  Kubernetes JSON schemas for core K8s resources, and schemastore.org for standard files.

## Quality Assurance & Validation

**ESSENTIAL VALIDATION SEQUENCE - Claude MUST run ALL steps after changes:**

1. **Flux Testing**: `./scripts/flux-local-test.sh` (changed files) or `./scripts/flux-local-test.sh
   --all`
2. **Pre-commit Checks**: `pre-commit run --all-files` (or `pre-commit run --files <files>`)
3. **Additional Validation**: kustomize build → kubectl dry-run (server) → flux check

**REQUIRED TOOLS FOR VERIFICATION:**

- **Helm Validation**: `helm template <release> <chart>` and `helm search repo <chart> --versions`
- **Chart Analysis**: `helm show values <chart>/<name> --version <version>` for secret integration
- **Configuration Testing**: `./scripts/test-renovate.sh` for renovate config validation

**Claude MUST NOT proceed to user commit without completing flux-local-test.sh and pre-commit
validation.**

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
- **Namespace Inheritance**: Use parent kustomization's `namespace` field and patches for automatic inheritance
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
  - Children: Individual app ks.yaml files NEVER specify `metadata.namespace` or `spec.targetNamespace`
  - Semantics: Parent's `namespace` field sets `metadata.namespace`, patch adds `spec.targetNamespace`
  - Result: App kustomizations live in correct namespace and deploy resources to same namespace automatically
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

## ConfigMap & Reloader Strategy

**IMPORTANT:** Use stable names (`disableNameSuffixHash: true`) ONLY for:

- Helm `valuesFrom` references (external-dns, cloudflare-dns)
- App-template `persistence.name` references (homer, cloudflare-tunnel)
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
- **App-Template Priority**: Use app-template `route` field over standalone HTTPRoute when possible
- **Health Probes**: NEVER use executable commands
- **Hostnames**: Use shortest resolvable form, avoid FQDNs when unnecessary

## Stack Overview

Talos K8s + Flux GitOps: Talos Linux, Flux v2, SOPS/Age, Rook Ceph + NFS, Taskfile, mise, talhelper.

## Essential Commands

- **Setup**: `mise trust .mise.toml && mise install`
- **Sync**: `task reconcile`
- **Validate**: See "Quality Assurance & Validation" section above
- **List Tasks**: `task --list`

**Note**: Taskfile includes for `bootstrap` and `talos` are referenced but taskfiles don't exist
yet.

## GitOps Flow

1. Modify `kubernetes/` manifests
2. **VALIDATION** (See "Quality Assurance & Validation" section above)
3. **USER COMMITS/PUSHES** (not Claude)
4. Flux auto-applies
5. Optional: `task reconcile` for immediate sync

**Flux Structure**: `flux-system` GitRepository → `cluster-meta` → `cluster-apps` → app ks.yaml
files

## Cluster Info

**Network**: `192.168.1.0/24`, Gateway: `192.168.1.1`, API: `192.168.1.70` **Gateways**: DNS
`192.168.1.71`, Internal `192.168.1.72`, External `192.168.1.73` **Tunnel**:
`6b689c5b-81a9-468e-9019-5892b3390500` → `192.168.1.73`

**Nodes**:

- rias: `192.168.1.61` (VM), nami: `192.168.1.50` (NUC), marin: `192.168.1.59` (NUC)

**Storage**: Rook Ceph (distributed), NFS from Nezuko `192.168.1.58` (Media 100Ti, Photos 10Ti,
FileRun 5Ti), Garage S3 `192.168.1.58:3900`

## Directory Structure

**Pattern**: `kubernetes/apps/<namespace>/<app>/`

**Standard Files**: helmrelease.yaml, ks.yaml, kustomization.yaml, secret.sops.yaml, httproute.yaml,
pvc.yaml **Asset Subdirs**: config/, resources/, icons/ (only when needed) **Namespace
Kustomization**: Lists all app ks.yaml files

**Key Namespaces**: kube-system, flux-system, network, rook-ceph, nfs, cert-manager, default,
dns-private

## Intel GPU for Applications

**IMPORTANT GPU PATTERNS:**

- **Resource Request**: `gpu.intel.com/i915: 1` for Intel GPU allocation
- **supplementalGroups**: Use minimal `[44, 104]` (video, render) for Intel GPU device access
- **OpenVINO**: Set `OPENVINO_DEVICE: GPU` for hardware ML acceleration
- **Media**: Use render device script for multi-GPU VA-API/QSV workloads

## Critical Security

**SOPS**: Encrypted files MUST NEVER be committed unencrypted **External-DNS**: Auto-manages DNS for
new services **Scripts**: See @scripts/CLAUDE.md for available automation scripts and usage

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

- **app-scout.sh**: Kubernetes migration discovery tool
- **bootstrap-apps.sh**: Application bootstrap for cluster initialization
- **flux-local-test.sh**: **ESSENTIAL VALIDATION** - Run flux-local test on modified files or entire
  repository
  - Usage: `./scripts/flux-local-test.sh [--all]`
  - Default: tests only changed files; `--all` tests entire repository
  - **REQUIRED** in validation sequence (see "Quality Assurance & Validation" section)
- **test-renovate.sh**: Test renovate configuration with debug output
  - Usage: `./scripts/test-renovate.sh`
  - Shows actual PR titles and validates renovate config locally
- **update-gitignore/**: Modular gitignore generation system
  - Usage: `./scripts/update-gitignore/update.sh`
  - Combines custom patterns from `custom/` with gitignore.io templates
