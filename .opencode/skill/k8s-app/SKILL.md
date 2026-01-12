---
name: k8s-app
description: Kubernetes app patterns for Flux GitOps - file templates, naming conventions, storage rules, components
---

# Kubernetes App Patterns

Load this skill before creating or modifying cluster apps.

## File Structure

Every app lives in `kubernetes/apps/{namespace}/{app}/` with these files:

| File                | Purpose                                       | Required               |
|---------------------|-----------------------------------------------|------------------------|
| ks.yaml             | Flux Kustomization - deployment orchestration | Yes                    |
| kustomization.yaml  | Kustomize - resource list, components         | Yes                    |
| helmrelease.yaml    | HelmRelease - app configuration               | Yes                    |
| pvc.yaml            | PersistentVolumeClaims                        | If stateful            |
| externalsecret.yaml | Secrets from Infisical                        | If secrets needed      |
| config/             | Files for configMapGenerator                  | If config files needed |

## ks.yaml (Flux Kustomization)

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/kustomization-kustomize-v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app example-app
spec:
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  dependsOn:
  - name: rook-ceph-cluster
    namespace: rook-ceph
  - name: global-config
    namespace: flux-system
  interval: 1h
  path: ./kubernetes/apps/{namespace}/{app}
  prune: true
  retryInterval: 2m
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: {namespace}  # Sets namespace for ALL resources
  timeout: 5m
  wait: false
  postBuild:
    substituteFrom:
    - kind: Secret
      name: cluster-secrets
    substitute:
      APP: example-app
      VOLSYNC_PVC: example-app  # Only if using volsync component
```

**Key rules:**

- `targetNamespace` sets namespace (NOT metadata.namespace)
- `dependsOn: global-config` required if using cluster-secrets substitution
- `dependsOn: rook-ceph-cluster` required if using ceph storage
- `postBuild.substitute.APP` required if using volsync component

## kustomization.yaml (Kustomize)

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization.json
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
components:
- ../../../components/volsync      # Optional: backup replication
- ../../../components/nfs-scaler   # Optional: KEDA scaler for NFS
resources:
- ./externalsecret.yaml
- ./helmrelease.yaml
- ./pvc.yaml
```

**Key rules:**

- NO namespace field (inherited from parent)
- List all resources explicitly
- Components are optional based on app needs

## helmrelease.yaml (App-Template)

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/helmrelease-helm-v2.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: example-app
spec:
  interval: 1h
  chartRef:
    kind: OCIRepository
    name: app-template
    namespace: flux-system  # REQUIRED - OCIRepository lives in flux-system
  values:
    controllers:
      example-app:  # MUST match HelmRelease metadata.name
        strategy: Recreate  # REQUIRED for RWO volumes
        annotations:
          reloader.stakater.com/auto: "true"
        pod:
          securityContext:
            fsGroup: 1000
            fsGroupChangePolicy: OnRootMismatch
        containers:
          app:
            image:
              repository: ghcr.io/home-operations/example
              tag: 1.0.0
            env:
              TZ: America/Chicago
            securityContext:
              runAsUser: 1000
              runAsGroup: 1000
              runAsNonRoot: true
              allowPrivilegeEscalation: false
              readOnlyRootFilesystem: true
              capabilities:
                drop: [ALL]
            probes:
              liveness: &probes
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /ping  # App-specific health endpoint
                    port: *port
              readiness: *probes
            resources:
              requests:
                cpu: 100m
                memory: 256Mi
              limits:
                memory: 1Gi

    service:
      app:
        controller: example-app
        ports:
          http:
            port: 8080

    persistence:
      config:
        existingClaim: example-app
        advancedMounts:
          example-app:  # Controller name
            app:        # Container name
            - path: /config
      tmp:
        type: emptyDir
        advancedMounts:
          example-app:
            app:
            - path: /tmp

    route:
      app:
        hostnames: ["example.${SECRET_DOMAIN}"]
        parentRefs:
        - name: internal
          namespace: network
          sectionName: https
```

**Critical rules:**

- `chartRef.namespace: flux-system` REQUIRED (OCIRepository location)
- Controller name MUST match HelmRelease name
- `strategy: Recreate` REQUIRED for RWO volumes (prevents Multi-Attach errors)
- ALWAYS use `advancedMounts` (even for RWX/emptyDir for consistency)
- Format: `advancedMounts: {controller}: {container}: - path: /path`

## helmrelease.yaml (External Chart)

For non-app-template charts, use `chart.spec.sourceRef` with local HelmRepository:

```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: example-charts
spec:
  interval: 2h
  url: https://charts.example.com
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: example
spec:
  interval: 1h
  chart:
    spec:
      chart: example
      version: 1.0.0
      sourceRef:
        kind: HelmRepository
        name: example-charts
  values:
    # Chart-specific values
```

## pvc.yaml

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/v1.30.3-standalone-strict/persistentvolumeclaim-v1.json
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: example-app  # Primary PVC matches app name
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 5Gi
  storageClassName: ceph-block
```

**Storage types:**

| Type            | Access | Strategy      | Use Case           |
|-----------------|--------|---------------|--------------------|
| ceph-block      | RWO    | Recreate      | Config, databases  |
| ceph-filesystem | RWX    | RollingUpdate | Shared data        |
| NFS             | RWX    | RollingUpdate | Media, large files |

**Naming:** Primary PVC = app name. Additional PVCs = `{app}-{purpose}` (e.g., `radarr-cache`)

## externalsecret.yaml

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/external-secrets.io/externalsecret_v1.json
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: example-app
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: infisical
  target:
    name: example-app-secret  # Kubernetes secret name
    creationPolicy: Owner
  data:
  - secretKey: API_KEY  # Key in Kubernetes secret (app's expected format)
    remoteRef:
      key: /namespace/example-app/api-key  # Infisical path (kebab-case)
```

**Path format:** `/namespace/app-name/secret-name` **Add secrets:** `task infisical:add-secret --
/namespace/app-name/secret-name "value"`

## Multi-Controller Apps

For apps with multiple processes (like Immich):

```yaml
controllers:
  main-app:
    containers:
      main:
        image: ...
  worker:
    containers:
      main:
        image: ...
  redis:
    containers:
      main:
        image: ...

service:
  main-app:
    controller: main-app
    ports:
      http:
        port: 8080
  worker:
    controller: worker
    ports:
      http:
        port: 9000
  redis:
    controller: redis
    ports:
      http:
        port: 6379

persistence:
  data:
    advancedMounts:
      main-app:
        main:
        - path: /data
      worker:
        main:
        - path: /data
```

## Volsync Component

For backup replication, add to kustomization.yaml:

```yaml
components:
- ../../../components/volsync
```

Required variables in ks.yaml:

```yaml
postBuild:
  substituteFrom:
  - kind: Secret
    name: cluster-secrets
  substitute:
    APP: example-app
    VOLSYNC_PVC: example-app  # Default: APP value
    # For ceph-filesystem PVCs, MUST override:
    # VOLSYNC_STORAGECLASS: ceph-filesystem
    # VOLSYNC_SNAPSHOTCLASS: csi-ceph-filesystem
```

## Intel GPU (DRA)

For apps requiring Intel GPU:

```yaml
# In ks.yaml dependsOn:
dependsOn:
- name: intel-gpu-resource-driver
  namespace: kube-system

# In helmrelease.yaml:
controllers:
  app:
    pod:
      nodeSelector:
        feature.node.kubernetes.io/custom-intel-gpu: "true"
      resourceClaims:
      - name: gpu
        resourceClaimTemplateName: app-name
    containers:
      main:
        resources:
          claims:
          - name: gpu

# Separate ResourceClaimTemplate in helmrelease.yaml values:
resourceClaimTemplates:
  app-name:
    spec:
      devices:
        requests:
        - name: gpu
          deviceClassName: gpu.intel.com
```

## Checklist: New App

1. [ ] Create directory `kubernetes/apps/{namespace}/{app}/`
2. [ ] Create ks.yaml with correct path, targetNamespace, dependencies
3. [ ] Create kustomization.yaml listing all resources
4. [ ] Create helmrelease.yaml with correct chartRef pattern
5. [ ] Create pvc.yaml if stateful (match storage type to strategy)
6. [ ] Create externalsecret.yaml if secrets needed
7. [ ] Add ks.yaml to parent `kubernetes/apps/{namespace}/kustomization.yaml`
8. [ ] Add secrets to Infisical: `task infisical:add-secret -- /namespace/app/key "value"`

## Common Mistakes

| Mistake                                  | Consequence        | Fix                            |
|------------------------------------------|--------------------|--------------------------------|
| RWO + RollingUpdate                      | Multi-Attach error | Use `strategy: Recreate`       |
| Missing `chartRef.namespace`             | Chart not found    | Add `namespace: flux-system`   |
| `metadata.namespace` in resources        | Breaks inheritance | Remove, use parent's namespace |
| `chart.spec.sourceRef` for app-template  | Wrong pattern      | Use `chartRef`                 |
| globalMounts with RWO                    | Potential issues   | Use `advancedMounts`           |
| postBuild.substituteFrom for app secrets | Race condition     | Use envFrom + ExternalSecret   |
