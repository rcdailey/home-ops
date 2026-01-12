# Home-Ops

Kubernetes homelab managed with Flux GitOps. Repository: `rcdailey/home-ops`

## Reference Repositories

Consult these for patterns and precedent:

- onedr0p/home-ops
- bjw-s-labs/home-ops
- buroa/k8s-gitops
- m00nwtchr/homelab-cluster

## Constraints

### GitOps

- NEVER run `git commit/push` without explicit user request
- NEVER use `kubectl apply/create/patch` - modify manifests only
- NEVER use `kubectl port-forward` - use kubectl exec, debug pods, or HTTPRoute

### Storage

- RWO volumes MUST use `strategy: Recreate` - RollingUpdate causes Multi-Attach errors
- RWO volumes REQUIRE `advancedMounts` - explicit controller/container specification
- Jobs/CronJobs with RWO PVCs MUST use native sidecar pattern (initContainers with `restartPolicy:
  Always`)

### Namespaces and Resources

- NEVER specify `metadata.namespace` in app resources - breaks inheritance from parent
  kustomization.yaml
- App ks.yaml uses `spec.targetNamespace` (exception to inheritance rule)
- chartRef REQUIRES `namespace: flux-system` for app-template OCIRepository

### Secrets and Configuration

- NEVER use `secret.sops.yaml` files - use ExternalSecret with Infisical
- NEVER use `postBuild.substituteFrom` for app secrets - race condition with ExternalSecret
- ONLY use `postBuild.substituteFrom` for: cluster-secrets, email-secrets
- NEVER use raw ConfigMap resources - use configMapGenerator with files from config/
- NEVER inline VRL source in vector.yaml - separate .vrl file required for testing

### Networking

- HTTPRoute ONLY for routing (never Ingress)
- NEVER configure External-DNS on HTTPRoutes (Gateways only)
- NEVER create LoadBalancer without user discussion

## Commands

```bash
# Setup
mise trust .mise.toml && mise install

# Reconcile cluster
task reconcile

# Flux operations
flux reconcile hr NAME -n NAMESPACE --force
flux reconcile hr NAME -n NAMESPACE --force --with-source  # Refresh source
flux reconcile hr NAME -n NAMESPACE --force --reset        # Clear retry backoff

# Helm (check values before configuring)
helm show values CHART
helm template RELEASE CHART

# Talos (one node at a time)
task talos:generate-config                    # After config changes, run once
task talos:apply-node IP=192.168.1.X          # Apply to each node sequentially
talosctl SUBCOMMAND OPTIONS -n NODEIP         # -n toward end
```

Scripts in `./scripts/` - use `--help` for usage:

- query-vm.py: VictoriaMetrics queries, alerts, discovery
- query-victorialogs.py: Log queries
- ceph.sh: Ceph commands via rook-ceph-tools
- test-vector-config.py: Vector VRL validation (required for Vector changes)
- validate-vmrules.sh: VMRule syntax validation

## Project Structure

```txt
kubernetes/apps/{namespace}/{app}/
  ks.yaml           Flux Kustomization (spec.targetNamespace)
  kustomization.yaml    Kustomize resources list, components
  helmrelease.yaml  HelmRelease (chartRef or chart.spec.sourceRef)
  pvc.yaml          PersistentVolumeClaims
  externalsecret.yaml   Infisical secrets
  config/           Files for configMapGenerator
```

Parent kustomization.yaml sets namespace, lists app ks.yaml files.

**Load the `k8s-app` skill before creating or modifying apps.** Update the skill when conventions
change.

## Conventions

### Naming

- App/service names: no `cluster-apps-` prefix
- Controller name MUST match HelmRelease name (produces `app` not `app-main`)
- Single service: HelmRelease name; multiple: append key (`plex`, `plex-api`)
- PVC: primary = app name; additional = `{app}-{purpose}`
- Internal hostnames: `service.namespace` (no `.svc.cluster.local`)

### Containers

- Primary: `ghcr.io/home-operations/*` (rootless, multi-arch, semver)
- Secondary: `ghcr.io/onedr0p/*`
- Avoid: `ghcr.io/hotio/*`, s6-overlay, gosu
- NEVER use `latest`, `rolling`, or non-semantic tags
- command/args: bracket notation `["cmd", "arg"]`

### Configuration

- `reloader.stakater.com/auto: "true"` on ALL apps
- Timezone: America/Chicago
- YAML language-server directive at top of files
- Prefer defaults by omission over explicit configuration
- Domain references: `${SECRET_DOMAIN}` (never real domain in manifests)

### Security

- Container: runAsUser/runAsGroup 1000, runAsNonRoot true, allowPrivilegeEscalation false,
  readOnlyRootFilesystem true, capabilities drop ALL
- Pod: fsGroup 1000, fsGroupChangePolicy OnRootMismatch

### Probes

- Liveness and Readiness: ALWAYS enable both
- Startup: OMIT unless slow initialization requires it
- httpGet with app health endpoint (e.g., `/ping`, `/health`) preferred over TCP
- Use YAML anchor (`&probes` / `*probes`) to share spec between liveness and readiness
- Omit default values (initialDelaySeconds: 0, periodSeconds: 10, timeoutSeconds: 1,
  failureThreshold: 3)

### Databases

- NEVER share databases between apps
- PostgreSQL: CloudNativePG
- MariaDB: MariaDB Operator

## Environment

### Stack

- OS: Talos Linux
- Orchestration: Kubernetes + Flux v2
- Secrets: SOPS/Age + External Secrets Operator + Infisical
- Storage: Rook Ceph, NFS (Nezuko), Garage S3
- Automation: Taskfile, mise, talhelper

### Network

| Purpose            | Address           |
|--------------------|-------------------|
| Main subnet        | 192.168.1.0/24    |
| BGP (Cilium LB)    | 192.168.50.0/24   |
| Gateway (UDMP)     | 192.168.1.1       |
| Kubernetes API     | 192.168.1.70      |
| LB: Infrastructure | 192.168.50.71-.99 |
| LB: Applications   | 192.168.50.100+   |

### Nodes

| Role    | Name     | IP           |
|---------|----------|--------------|
| Control | hanekawa | 192.168.1.63 |
| Control | marin    | 192.168.1.59 |
| Control | sakura   | 192.168.1.62 |
| Worker  | lucy     | 192.168.1.54 |
| Worker  | nami     | 192.168.1.50 |

### Storage Backends

| Backend                       | Type             | Notes                                   |
|-------------------------------|------------------|-----------------------------------------|
| Rook Ceph                     | Block/Filesystem | ceph-block (RWO), ceph-filesystem (RWX) |
| NFS (192.168.1.58)            | Media, Photos    | /mnt/user/media, /mnt/user/photos       |
| Garage S3 (192.168.1.58:3900) | Backups          | postgres-backups, volsync-backups       |

Ceph toolbox: `kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph status`

### Intel GPU

- DRA via ResourceClaimTemplate with deviceClassName: gpu.intel.com
- Apps depend on intel-gpu-resource-driver in kube-system
- OpenVINO: `OPENVINO_DEVICE: GPU`

## Commits

Path-based conventional commits:

| Type     | Paths                                                   |
|----------|---------------------------------------------------------|
| ci       | .github/workflows/**, .taskfiles/**, Taskfile.yaml      |
| build    | renovate.json5, .renovate/**                            |
| chore    | .editorconfig, .gitignore, .yamllint.yaml, lint configs |
| docs     | *.md, docs/**, LICENSE                                  |
| feat     | New apps (kubernetes/apps/namespace/app/)               |
| fix      | Bug fixes, crash loops, probe failures, alerts          |
| refactor | Resource reorganization, no behavior change             |

Breaking changes (type!:): API/CRD upgrades, storage migrations

Examples: `fix(plex): resolve crash loop`, `feat(bookstack): add wiki app`
