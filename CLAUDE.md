# Claude Directives

## Critical Operational Rules

**IMPORTANT:** Claude MUST:

- **Git Protocol**: NEVER run `git commit`/`git push` without explicit user request. GitOps requires
  user commits, not Claude. STOP after changes and wait for user to commit/push.
- **Task Priority**: Use `task` commands over CLI. Check `Taskfile.yaml` first.
- **Validation**: Run `pre-commit run --all-files` after changes, before user commits.
- **Reference Format**: Use `file.yaml:123` format when referencing code.
- **Configuration**: Favor YAML defaults over explicit values for cleaner manifests.
- **Domain References**: NEVER reference real homelab domain names in documentation or config files.
  Use `domain.com` for examples or `${SECRET_DOMAIN}` in YAML manifests.

## Deployment Standards

**CRITICAL FLUX PATTERNS:**

- **GitRepository**: ALWAYS use `flux-system` name, verify sourceRef matches existing Kustomizations
- **App-Template**: Use bjw-s OCIRepository with `chartRef: {kind: OCIRepository, name:
  app-template}`, HTTPRoute over Ingress, add `postBuild.substituteFrom: cluster-secrets`
- **Directory Structure**: `kubernetes/apps/<namespace>/<app>/` - namespace dirs MUST match names
  exactly
- **File Organization**: All manifests co-located (helmrelease.yaml, ks.yaml, kustomization.yaml,
  secrets, pvcs). Subdirectories only for assets (config/, resources/, icons/)
- **Kustomization Logic**: Single ks.yaml for same namespace+timing+lifecycle. Multiple for
  different namespaces/timing/lifecycle or operator+instance patterns
- **Namespace Inheritance**: NEVER add `namespace` field to child ks.yaml files - parent
  Kustomizations with `namespace: <target>` automatically override ALL child resource namespaces.
  Adding redundant namespace fields creates confusion and maintenance overhead.
- **Validation Sequence**: kustomize build → kubectl dry-run (server) → flux check
- **Helm**: Check versions with `helm search repo <chart> --versions`, validate with `helm template`
- **Timing**: Never specify explicit timeouts/intervals without specific issue justification

## Storage & Secrets

**IMPORTANT PATTERNS:**

- **NFS**: Static PVs for existing data, PVCs in app dirs, subPath mounting
- **Database Isolation**: NEVER share databases between apps, deploy dedicated instances
- **Secret Integration Priority**: 1) `envFrom` at app, 2) `env.valueFrom`, 3) HelmRelease
  `valuesFrom`, 4) `postBuild.substituteFrom` (last resort)
- **Secret Management**: App-isolated secrets, `sops --set` for changes, `sops unset` for removal
- **Chart Analysis**: Run `helm show values <chart>/<name> --version <version>` to check secret
  integration capabilities before choosing method

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
- **Validate**: `pre-commit run --all-files` (or `pre-commit run --files <file1> <file2>`)
- **List Tasks**: `task --list`

**Note**: Taskfile includes for `bootstrap` and `talos` are referenced but taskfiles don't exist
yet.

## GitOps Flow

1. Modify `kubernetes/` manifests
2. `pre-commit run --all-files` (or `pre-commit run --files <changed_files>`)
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
FileRun 5Ti)

## Directory Structure

**Pattern**: `kubernetes/apps/<namespace>/<app>/`

**Standard Files**: helmrelease.yaml, ks.yaml, kustomization.yaml, secret.sops.yaml, httproute.yaml,
pvc.yaml **Asset Subdirs**: config/, resources/, icons/ (only when needed) **Namespace
Kustomization**: Lists all app ks.yaml files

**Key Namespaces**: kube-system, flux-system, network, rook-ceph, nfs, cert-manager, default,
dns-private

## Critical Security

**SOPS**: Encrypted files MUST NEVER be committed unencrypted **External-DNS**: Auto-manages DNS for
new services **App-Scout**: See @scripts/app-scout/README.md for deployment discovery patterns

## DNS Architecture

**AdGuard Home**: Subnet-based filtering with VLAN client overrides for network segmentation.

**Network Rules**:

- **Main LAN** (192.168.1.0/24): Global baseline (590k+ rules)
- **Privacy VLANs** (IoT/Work): Social media blocking
- **Kids VLAN**: Comprehensive content restrictions
- **Guest VLAN**: Adult content blocking
- **Cameras VLAN**: Minimal filtering for compatibility

**API Access**: `https://dns.${SECRET_DOMAIN}/control` (credentials in `dns-private-secret`)

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
