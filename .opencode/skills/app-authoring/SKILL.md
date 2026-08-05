---
name: app-authoring
description: >-
  Use when adding, restructuring, or reviewing an application under `kubernetes/apps/`; creating
  Flux Kustomizations, HelmReleases, PVCs, ExternalSecrets, HTTPRoutes, or app-template values; or
  choosing repository patterns for a new workload. Do NOT use for a narrow value change whose
  pattern is already established in the app.
---

# Application authoring

Create applications from current repository examples while preserving the root AGENTS.md
invariants. Do not introduce a pattern from another repository when a local example covers it.

## Choose the example

- Start with `kubernetes/apps/default/donetick/` for an app-template workload.
- Use `kubernetes/apps/media/plex/` for `configMapGenerator` and `config/` files.
- Use `kubernetes/apps/default/headlamp/` for a single-use external HelmRepository chart.
- Use `kubernetes/apps/default/immich/` for multiple controllers or Intel GPU DRA.

## Create the application

1. Create `kubernetes/apps/{namespace}/{app}/` with flat YAML resources.
2. Add `ks.yaml` with `spec.targetNamespace` and the required dependencies.
3. Add `kustomization.yaml` with every resource listed explicitly.
4. Add `helmrelease.yaml` using the chart pattern selected below.
5. Add `pvc.yaml` only when the workload is stateful.
6. Add `externalsecret.yaml` only when the application needs secrets.
7. Add the app's `ks.yaml` to the namespace `kustomization.yaml`.
8. Validate every changed file with `pre-commit run --files <files>`.

The user adds Infisical values with:

```bash
just infisical add-secret /namespace/app/key "value"
```

Do not run this command unless the user explicitly requests it.

## Flux Kustomization

- Set `spec.targetNamespace`; do not set `metadata.namespace` on app resources.
- Depend on `global-config` when using cluster-secret substitution.
- Depend on `rook-ceph-cluster` when using Ceph storage.
- Depend on `garage-instance` in namespace `storage` when using CNPG S3 backups.
- Set `postBuild.substitute.APP` when using the Volsync component.

## Kustomize

- Do not set `namespace`; the parent supplies it.
- List resources explicitly, including `pvc.yaml` only when it exists.
- Put generated configuration files under `config/`.
- Use `disableNameSuffixHash: true` only for cross-resource names such as Helm `valuesFrom` or a
  persistence reference.

## Helm chart source

For app-template, use `chartRef` and set `chartRef.namespace: flux-system`. Do not use
`chart.spec.sourceRef`.

For an external chart, use `chart.spec.sourceRef`. Keep a single-use HelmRepository beside the
application; put a source shared by multiple apps in `flux/meta/repos` with namespace
`flux-system`.

Put GitRepository sources for Flux Kustomizations in `flux/meta/repos`; an app Kustomization cannot
deploy the source it needs to build itself.

## Persistence

- The primary PVC matches the app name; additional PVCs use `{app}-{purpose}`.
- `ceph-block` is RWO and requires `Recreate` plus `advancedMounts`.
- `ceph-filesystem` and NFS are RWX and use `RollingUpdate`.
- Use NFS for media and other large shared files.
- Jobs and CronJobs with an RWO PVC use an init container with `restartPolicy: Always` as the
  native sidecar.

For Volsync, add the component and substitute `APP`. The defaults are `ceph-block` and
`csi-ceph-blockpool`. For CephFS, set `VOLSYNC_STORAGECLASS: ceph-filesystem` and
`VOLSYNC_SNAPSHOTCLASS: csi-ceph-filesystem`.

## Controllers and services

- Name the primary controller after the HelmRelease.
- A single service uses the release name. Multiple services append their service key.
- Give each process its own controller when an app has independent main, worker, or cache
  processes.
- Map persistence through `advancedMounts` for each controller and container.

## Secrets and configuration

- Use `ExternalSecret` with `external-secrets.io/v1` and path
  `/namespace/app-name/secret-name`.
- Prefer `envFrom`, then `env.valueFrom`, then HelmRelease `valuesFrom`.
- Use `configMapGenerator`; do not create raw ConfigMap resources.
- Use `postBuild.substituteFrom` only for the centrally managed `cluster-secrets` and
  `email-secrets` objects.

## Optional patterns

For Intel GPU DRA, follow the Immich machine-learning controller. Include its Flux dependency,
node selector, ResourceClaimTemplate, pod resource claim, container claim, and OpenVINO device
setting as one pattern; do not copy only part of it.
