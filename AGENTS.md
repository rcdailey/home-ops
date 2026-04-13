# Home-Ops Directives

## Tier 1: Breaking Rules

These rules prevent immediate cluster failures. Violations cause crashes, data corruption, or GitOps
drift.

### GitOps Mindset

**Every cluster change MUST flow through git.** Imperative commands are diagnostic only.

- **NEVER run git commit/push without explicit user request** - GitOps requires user commits for
  accountability. This includes using the commit subagent. Always wait for explicit "commit"
  request.
- **NEVER delete resources as a fix** - Deleting jobs, pods, or PVCs treats symptoms, not causes.
  Find the manifest issue and fix it. Exception: cleanup after root cause is fixed.
- **NEVER adjust health probes to fix failures** - Probes detect problems, they don't cause them.
  Investigate WHY the probe fails (resource exhaustion, slow startup, missing deps).

### Troubleshooting Approach

1. **Query**: Gather symptoms via subagent (alerts, logs, events, pod status)
2. **History**: `git log -p --follow --invert-grep --author="renovate" -- path/to/file.yaml` for
   recent changes
3. **Analyze**: Read manifests, check CRD specs, verify dependencies
4. **Research**: Subagent for reference repos, Context7, upstream docs
5. **Fix**: Modify manifests to address root cause
6. **Validate**: `pre-commit run --files <changed-files>`

Recurring issues indicate incomplete root cause analysis.

**All cluster queries MUST use `hops` commands** (`./scripts/hops.py`). Direct use of kubectl,
talosctl, helm, flux, and other cluster CLIs is prohibited except when `hops` lacks the needed
functionality (see escape hatch below). `hops` produces LLM-optimized, token-compact output by
design; raw CLI output wastes context on noise the LLM has to parse and discard.

**`hops` escape hatch:** `hops` is not feature-complete. When a command you need does not exist,
produces too much or too little output, or has a bug: (1) load the `hops` skill, (2) update or add
the command, (3) test the updated command, (4) use it to continue your original task. Do not work
around gaps by falling back to raw CLIs; fix the tool instead. If the gap is too complex to fix
inline, document it as a TODO in the relevant hops source file and fall back to the raw CLI for that
specific operation only.

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
- **ALWAYS include test data for VRL validation** - Use ./scripts/test-vrl.py for validation

### Scaling

- KEDA ScaledObjects create HPAs that continuously enforce replica counts
- To manually scale: pause ScaledObject first (`autoscaling.keda.sh/paused: "true"` annotation)

## Tier 2: Conventions

Consistency patterns for maintainability and clarity.

### Configuration Standards

- ALWAYS use chartRef (see Tier 1: Storage, Volumes, and Resource Patterns)
- ALWAYS include appropriate `# yaml-language-server:` directive at top of YAML files
- ALWAYS use reloader.stakater.com/auto: "true" for ALL apps (NEVER use targeted annotations)
- ALWAYS use rootless containers (security requirement)
- ALWAYS check existing applications before making changes
- When removing, renaming, or restructuring an app, MUST run `rg "name|alias|keyword"` at repo root
  to find all references (docs, AGENTS.md, Homepage, backup lists, S3 buckets, etc.) before
  committing
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
  service key (e.g., `plex` vs `plex-main`, `plex-api`). Using `app` as a single service key is also
  acceptable
- Controller naming: Primary controller MUST match HelmRelease name (e.g., `controllers: plex:` for
  release `plex`). This produces deployment `plex` instead of `plex-main`. App-template avoids
  `{release}-{release}` duplication when controller matches release.
- Primary: `ghcr.io/home-operations/*` containers (semantically versioned, rootless, multi-arch)
- Secondary: `ghcr.io/onedr0p/*` containers (if home-operations unavailable)
- Avoid: `ghcr.io/hotio/*` and containers using s6-overlay, gosu
- Prefer semantic versions for all production containers. Rolling tags (like `latest`) are
  acceptable for trivial init containers (e.g., alpine for file copying) where renovate upgrades add
  no value
- SHA256 digests: Automatically added by renovatebot
- Container command/args: Use bracket notation `command: ["cmd", "arg"]` instead of multi-line dash
  format for consistency
- ALWAYS use America/Chicago (or equivalent representation) for timezone if needed.
- SMTP: `smtp-relay.network:587` (no auth) - never configure app-specific SMTP credentials

### Topology Spread

The Talos scheduler is configured with a cluster-wide PodTopologySpread default: `ScheduleAnyway`,
`maxSkew: 1`, `topologyKey: kubernetes.io/hostname`. All pods prefer spreading across nodes
automatically. NEVER add explicit `topologySpreadConstraints` unless `DoNotSchedule` is required;
NEVER use `podAntiAffinity` for topology spreading. `ScheduleAnyway` (the scheduler default) is
sufficient for application-tier workloads. `DoNotSchedule` is for critical infrastructure where
co-location defeats the purpose of HA (e.g., DNS servers, database operators).

### Health Probes

- Probes default to off in app-template; only specify probes you need
- Liveness: ALWAYS enable with simple httpGet returning 200 (e.g., `/status`, `/health`, `/ping`)
- Readiness: OMIT for single-replica services (readiness controls traffic routing, irrelevant
  without HA). Only add readiness for multi-replica deployments where it should perform a more
  comprehensive check than liveness.
- Startup: OMIT unless slow initialization requires extended startup time
- Omit default values (initialDelaySeconds: 0, periodSeconds: 10, timeoutSeconds: 1,
  failureThreshold: 3)
- When liveness and readiness end up identical (no heavier endpoint exists): use a YAML anchor
  (`&probe` / `*probe`) to share the spec, and add a comment above `readiness:` explaining why no
  distinct endpoint is available

### Security and Networking

- OIDC client IDs: Hardcode as app name in env vars (not secret); only client secret needs Infisical
- HTTPRoute ONLY for all routing (never Ingress)
- NEVER configure External-DNS on HTTPRoutes (Gateways only)
- DNSEndpoint CRDs MUST carry `external-dns/provider: <provider>` label indicating which
  external-dns instance should manage them
- NEVER create LoadBalancer without explicit user discussion
- MCP sidecar routing: `mcp-{service-subdomain}.${SECRET_DOMAIN}` where `{service-subdomain}` is the
  app's existing hostname prefix (e.g., SearXNG at `search.${SECRET_DOMAIN}` gets MCP endpoint at
  `mcp-search.${SECRET_DOMAIN}`)
- Route backendRefs: Use full service name (e.g., radarr-app), not identifier (e.g., app)
- NEVER use wildcards for SecurityPolicy headers (always explicit headers)
- NEVER specify explicit timeouts/intervals without justification (use Flux defaults)
- Pod securityContext: runAsUser/runAsGroup 1000, runAsNonRoot true, fsGroup 1000,
  fsGroupChangePolicy OnRootMismatch (identity + volume ownership for all containers)
- Container securityContext: allowPrivilegeEscalation false, readOnlyRootFilesystem true,
  capabilities drop ALL (hardening only; these fields have no pod-level equivalent)
- NEVER duplicate identity fields (runAsUser, runAsGroup, runAsNonRoot) in container securityContext
  unless containers in the same pod require different UIDs

### Database and Logging

- NEVER share databases between apps (dedicated instances per app)
- Use CloudNativePG for PostgreSQL, MariaDB Operator for MariaDB
- NEVER create custom equivalents to standard Vector fields (message, timestamp, level, severity,
  host, source_type)
- VRL regex: Prefer non-greedy `.*?` over greedy `.*`
- Sidecar pattern: Regular containers for Deployments, initContainers with restartPolicy: Always for
  Jobs/CronJobs
- Vector log collection uses two paths: (1) daemonset collection via pod label
  `observability.home-ops/logs=true`, or (2) a Vector sidecar container for apps that need custom
  log parsing (e.g., file-based logs). Both paths deliver to VictoriaLogs.
- Multi-container pods: use `vector.dev/exclude-containers` pod annotation (comma-separated
  container names) to skip noisy sidecar logs. The daemonset collects all containers by default;
  exclude VPN tunnels, port-forward helpers, and other infrastructure sidecars.
- Vector sidecar containers MUST be named `vector` (not `vector-sidecar` or other variants)

### Documentation

- Validate markdown changes with `markdownlint-cli2` before committing
- Links: reference-style `[text][anchor]` with definitions at section end (not inline)
- NEVER use bold text as heading replacement - use actual `##` headings
- MUST hard-wrap at column 100
- Blank line required between headings, lists, code blocks, and other elements

**Outline vs docs/ boundary:** Outline (`docs.${SECRET_DOMAIN}`) is the household knowledge base for
home maintenance, pool care, media room, homelab reference, and hobby documentation. Content lives
in Outline when it changes independently of code, benefits from rich editing and search, or may be
referenced by non-technical users. The `docs/` directory is for content tightly coupled to the
codebase: ADRs, investigation journals, runbooks, and AGENTS.md directives that evolve through PRs
alongside manifests. Litmus test: if the content needs PR review with code changes, it belongs in
`docs/`; otherwise it belongs in Outline.

**Outline MCP integration:** Outline exposes a built-in MCP endpoint at `docs.${SECRET_DOMAIN}/mcp`.
Use the Outline MCP tools (search, read, create, update documents and collections) to manage Outline
content directly. SHOULD proactively use Outline MCP tools when the user asks to create, update, or
organize documentation that belongs in Outline per the boundary above.

### Investigations

When documenting a debugging session:

1. MUST read `docs/investigations/TEMPLATE.md` for structure
2. Create `docs/investigations/{component}-{brief-description}-{YYYY-MM-DD}.md`
3. Extract any durable design decisions into separate ADRs in `docs/decisions/`
4. Cross-reference between investigation and ADR(s)

Investigation docs are historical snapshots, not living documents. If conclusions become stale due
to infrastructure changes, the ADR supersession chain captures that; do not update old investigation
docs.

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
- dsluo/homelab
- aclerici38/home-ops

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
  investigations/     Historical debugging journals (not prescriptive guides)
  memory-bank/        Ephemeral context, temporary workarounds (remove when stale)
  reference/          Standalone reference material (OIDC patterns, protocol guides)
  runbooks/           Step-by-step operational procedures
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

Copy patterns from exemplary apps rather than using synthetic templates. These apps follow all Tier
1 and Tier 2 conventions:

**Canonical example (start here):** `kubernetes/apps/default/donetick/`

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

**User-only commands** (agents MUST NOT run these): `just reconcile`, `flux reconcile`, `helm
template`, `just talos diff-config`/`just talos apply-node`, `talosctl`. Use `hops flux values` and
`hops flux defaults` instead of `helm show values`/`helm get values`. Standalone scripts:
`./scripts/test-vrl.py` (VRL validation), `./scripts/icon-search.py` (dashboard icons),
`./scripts/hass-api.py` (Home Assistant API).

**Conventional commits:**

Type is determined by intent (what the change accomplishes), not by filename. Path patterns below
identify unambiguous cases where a single type always applies; everything else requires reading the
diff.

The primary product of this repository is the cluster. `feat` and `fix` describe changes to the
cluster's behavior (new apps, bug fixes, alert resolutions). Changes that only affect developer
tooling, CI, or documentation are never `feat` or `fix` unless they accompany a cluster change in
the same commit.

Path-determined types (path alone decides):

- ci: `.github/workflows/**`, `.justfiles/**`, .justfile
- build: renovate.json5, `.renovate/**`
- chore: .editorconfig, .gitignore, .yamllint.yaml, .markdownlint-cli2.yaml, .pre-commit-config.yaml
- docs: `docs/**`, LICENSE, SECURITY.md, CODEOWNERS

Intent-determined types (diff content decides):

- `kubernetes/**`: feat (new app/service directory), fix (bug fixes, crash loops, probe failures,
  resource issues, alert resolutions), refactor (reorganization, no behavior change)
- `scripts/**`: chore (new script or capability), fix (bug fix that fixes cluster behavior)
- `.opencode/**`: chore (new skill, agent, or command), fix (bug fix that fixes cluster behavior)
- Root `*.md` (AGENTS.md, README.md, etc.): docs when prose-only; use the type matching the
  co-changed domain when the markdown change accompanies code (e.g., adding a skill + its AGENTS.md
  routing entry is chore, not docs)
- Breaking (append `!` after scope): API/CRD upgrades, incompatible Helm upgrades, storage
  migrations

Scope format by domain:

- `kubernetes/**`: app name from directory (e.g., `plex`, `bookstack`)
- `scripts/**`: script name without extension (e.g., `hass-api`, `hops`)
- `.opencode/**`: component name (e.g., skill name `home-assistant`, agent name `commit`)
- `flux/**`, `talos/**`: component or subsystem name
- Omit scope for repo-wide changes that span multiple domains

Mixed-path commits: when a single commit spans multiple domains (e.g., a script + its AGENTS.md
entry), use the type and scope of the primary change. The primary change is the one that provides
the new behavior; supporting changes (docs updates, routing entries) are secondary.

Examples: `fix(plex): resolve crash loop`, `feat(bookstack): add wiki documentation app`,
`chore(home-assistant): add API integration skill`, `docs: update investigation template`

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
- AT&T Fiber Gateway: BGW320-505 (IP passthrough to UDMP)
- Gateway (Unifi UDMP): 192.168.1.1
- Kubernetes API: 192.168.1.70
- LoadBalancer IPs (Cilium IPAM): 192.168.50.71-.99 (infrastructure), 192.168.50.100+ (applications)

**Cluster nodes:**

- Control plane: hanekawa (192.168.1.63), marin (192.168.1.59), sakura (192.168.1.62)
- Workers: lucy (192.168.1.54), nami (192.168.1.50)

**Node storage devices:**

Every node has two physical drives: `sda` (SATA, Talos system disk) and `nvme0n1` (NVMe, Ceph OSD).
When interpreting disk metrics, `sda` is always the OS disk and `nvme0n1` is always the Ceph data
disk. The `rbd*` devices are Ceph RBD block devices mapped by CSI (not physical disks).

| Node     | sda (Talos)           | nvme0n1 (Ceph OSD)               |
| -------- | --------------------- | -------------------------------- |
| hanekawa | Samsung 870 EVO 250GB | Samsung 970 EVO Plus 1TB (OSD.5) |
| marin    | Samsung 870 EVO 250GB | Samsung 970 EVO Plus 1TB (OSD.2) |
| sakura   | Samsung 870 EVO 250GB | Samsung 970 EVO Plus 1TB (OSD.4) |
| lucy     | SanDisk SDSSDH32 2TB  | Crucial P3 2TB (OSD.3)           |
| nami     | Crucial BX500 2TB     | Samsung 990 PRO 2TB (OSD.0)      |

**Storage backends:**

- Rook Ceph: Distributed block/filesystem storage across cluster nodes
- NFS (Nezuko 192.168.1.58): Media (100Ti), Photos (10Ti)
- Garage S3 (192.168.1.58:3900): Region garage, buckets: postgres-backups
- Volsync: Kopia repository on NFS (Nezuko /mnt/user/volsync), shared single repository with per-app
  isolation via snapshot identity
- CloudNativePG: Barman WAL archiving to s3://postgres-backups/{cluster}/
- Ceph toolbox: `./scripts/hops.py storage ceph status` (or `osd`, `io`)

**`hops` CLI:** Run `./scripts/hops.py --help` for domains, `./scripts/hops.py <domain> --help` for
commands. Key entry point for debugging: `./scripts/hops.py app diagnose APP [-n NS]` (works for
both workload apps and gateway-only external services).

### New App Checklist

1. Create directory `kubernetes/apps/{namespace}/{app}/`
2. Create ks.yaml with correct path, targetNamespace, dependencies
3. Create kustomization.yaml listing all resources
4. Create helmrelease.yaml with correct chartRef pattern
5. Create pvc.yaml if stateful (match storage type to strategy)
6. Create externalsecret.yaml if secrets needed
7. Add ks.yaml to parent `kubernetes/apps/{namespace}/kustomization.yaml`
8. Add secrets to Infisical: `just infisical add-secret /namespace/app/key "value"`
