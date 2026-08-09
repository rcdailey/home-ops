# Home-Ops Directives

## Tier 1: Breaking Rules

These rules prevent immediate cluster failures. Violations cause crashes, data corruption, or GitOps
drift.

### GitOps Mindset

**Every persistent cluster change MUST flow through git.** Imperative commands are diagnostic only
unless permitted below.

- **NEVER run git commit/push without explicit user request** - GitOps requires user commits for
  accountability. This includes using the commit subagent. Always wait for explicit "commit"
  request.
- **NEVER delete resources as a fix** - Deleting jobs, pods, or PVCs treats symptoms, not causes.
  Find the manifest issue and fix it.
- **Orphan cleanup MUST be operational, not declarative** - An exact, non-data-bearing object absent
  from Git and without an active GitOps owner MUST be deleted with the underlying cluster CLI after
  verification through `hops`. NEVER create temporary manifests solely to adopt and prune orphans.
  PVCs, PVs, and namespaces are excluded from this exception.
- **NEVER adjust health probes to fix failures** - Probes detect problems, they don't cause them.
  Investigate WHY the probe fails (resource exhaustion, slow startup, missing deps).

### Troubleshooting Approach

1. **Query**: Gather symptoms via subagent (alerts, logs, events, pod status)
2. **History**: `git log -p --follow --invert-grep --author="renovate" -- path/to/file.yaml` for
   recent changes
3. **Analyze**: Read manifests, check CRD specs, verify dependencies
4. **Research**: Subagent for reference repositories and upstream documentation
5. **Fix**: Modify manifests to address root cause
6. **Validate**: `pre-commit run --files <changed-files>`

Recurring issues indicate incomplete root cause analysis.

**All cluster queries MUST use `hops` commands** (`./scripts/hops.sh`). Direct use of kubectl,
talosctl, helm, flux, and other cluster CLIs for queries is prohibited except when `hops` lacks the
needed functionality (see escape hatch below). `hops` produces LLM-optimized, token-compact output
by design; raw CLI output wastes context on noise the LLM has to parse and discard.

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
- **NEVER read, reference, or document `.local` files** (e.g., `.mise.local.toml`, `.envrc.local`).
  These are unversioned and contain secrets/credentials that MUST NOT appear in agent output,
  commits, or documentation.

### Scaling

NFS-dependent apps use the `nfs-scaler` component. It creates an HPA that scales from zero to one
using the external `probe_success` metric. The API server has `HPAScaleToZero` enabled.

## Tier 2: Conventions

### Acceptance

Changes in this repository MUST NOT receive an independent acceptance audit. The primary validates
changes directly with repository checks.

### Application configuration

- Include the appropriate `# yaml-language-server:` directive in YAML files.
- Use `reloader.stakater.com/auto: "true"`, never targeted reloader annotations.
- Use rootless containers and prefer YAML defaults by omission.
- Explain only non-obvious exceptions, limitations, and workarounds in comments.
- Do not use the `cluster-apps-` prefix.
- Use `${SECRET_DOMAIN}` instead of real homelab domains in examples and manifests.
- Use `service.namespace` for internal addresses, without `svc.cluster.local`.
- Use bracket notation for container commands and arguments.
- Use America/Chicago when an application needs a timezone.
- Use `smtp-relay.network:587` without application-specific SMTP credentials.

When removing, renaming, or restructuring an app, search the repository for its name, aliases, and
related identifiers before finalizing the change. This includes Homepage, backups, and bucket names.

Load the `app-authoring` skill for new applications or structural application changes.

### Containers and topology

Prefer semantically versioned, rootless, multi-architecture images from `ghcr.io/home-operations/*`,
then `ghcr.io/onedr0p/*`. Avoid Hotio, s6-overlay, and gosu images. Renovate adds digests. Rolling
tags are acceptable only for trivial init containers.

The scheduler already applies `ScheduleAnyway` topology spreading with hostname skew 1. Do not add
explicit topology spreading or pod anti-affinity unless critical infrastructure requires
`DoNotSchedule`.

### Health probes

- Enable a simple HTTP liveness probe.
- Omit readiness for single-replica services.
- Add readiness for multiple replicas only when it is more comprehensive than liveness.
- Omit startup probes unless initialization is slow.
- Omit probe defaults.
- If readiness must match liveness, share the spec with a YAML anchor and explain why.

### Security and networking

- Hardcode an OIDC client ID as the app name; store only the client secret in Infisical.
- Use HTTPRoute, never Ingress.
- Configure External-DNS on Gateways, not HTTPRoutes.
- Label DNSEndpoints with `external-dns/provider: <provider>`.
- Discuss any new LoadBalancer with the user before creating it.
- Route MCP sidecars at `mcp-{service-subdomain}.${SECRET_DOMAIN}`.
- Use full generated service names in route backend references.
- Use explicit SecurityPolicy headers, never wildcards.
- Do not set timeouts or intervals without a concrete reason.

Pod security contexts use UID and GID 1000, `runAsNonRoot`, `fsGroup: 1000`, and
`fsGroupChangePolicy: OnRootMismatch`. Container contexts disable privilege escalation, use a
read-only root filesystem, and drop all capabilities. Do not duplicate identity fields at container
level unless containers need different identities.

### Databases and logging

- Give every application its own database.
- Use CloudNativePG for PostgreSQL and MariaDB Operator for MariaDB.
- CNPG clusters require at least two instances so their PDB does not block node drains.
- Decide CNPG S3 backups case by case; when required, use the `cnpg-backup` component and follow
  `docs/architecture/backup-strategy.md`.
- Each CNPG cluster needs its own GarageS3Bucket to avoid permission races.
- Use a regular Vector sidecar for Deployments and a native sidecar for Jobs and CronJobs.
- Name Vector sidecars `vector`.
- Exclude noisy infrastructure sidecars with `vector.dev/exclude-containers`.
- Use `observability.home-ops/logs=true` for daemonset collection.

Load the `vrl-authoring` skill for VRL programs and parser fixtures.

### Documentation

- Validate Markdown with `markdownlint-cli2`.
- Use reference-style links, real headings, 100-column wrapping, and required blank lines.

Outline is for household and homelab knowledge that changes independently of code or serves
non-technical readers. Repository `docs/` is for ADRs, investigations, runbooks, and reference
material that evolves with code. Load `outline-cli` for Outline operations.

When documenting an investigation, read `docs/investigations/TEMPLATE.md`, create a dated document,
move durable decisions into ADRs, and cross-reference them. Investigations are historical snapshots;
do not update them when later decisions supersede their conclusions.

## Reference and operations

This repository is `rcdailey/home-ops`. Current cluster inventory is in
`docs/reference/cluster-inventory.md`.

Check local applications first. When no local pattern covers the requirement, consult these
reference repositories before designing a new pattern:

- onedr0p/home-ops
- bjw-s-labs/home-ops
- buroa/k8s-gitops
- m00nwtchr/homelab-cluster
- dsluo/homelab
- aclerici38/home-ops

Agents MUST NOT run `just reconcile`, `flux reconcile`, `helm template`, `just talos diff-config`,
or `just talos apply-node`. Use `hops flux values` and `hops flux defaults` instead of Helm values
commands.

Run standalone script help before use rather than relying on a command catalog in this file.

### Conventional commits

Choose the type by intent. Cluster behavior uses `feat`, `fix`, or `refactor`; developer tooling
uses `chore`; CI uses `ci`; Renovate configuration uses `build`; prose-only documentation uses
`docs`. Use `!` for incompatible API or CRD upgrades, storage migrations, and other breaking
changes.

Use the app name as scope for `kubernetes/**`, script name for `scripts/**`, component name for
`.opencode/**`, and subsystem for `flux/**` or `talos/**`. Omit scope for repository-wide changes.
For mixed paths, use the type and scope of the change that provides the behavior.
