# Volsync Backup Rollout

Tracking the configuration of volsync backups for apps not currently backed up.

## PV-Migrate Usage Reference

### Recommended Syntax

```bash
kubectl pv-migrate \
  --source <source-pvc> \
  --source-namespace <source-ns> \
  --source-path <path-in-pvc> \
  --dest <dest-pvc> \
  --dest-namespace <dest-ns> \
  --dest-path <path-in-pvc> \
  --strategies <strategy>
```

**Note:** The `migrate` subcommand exists but is legacy. Use the root command directly as shown
above.

### Key Flags

- `-n, --source-namespace`: Namespace of source PVC
- `-p, --source-path`: Filesystem path within source PVC (default: `/`)
- `-R, --source-mount-read-only`: Mount source as ReadOnly (default: `true`)
- `-N, --dest-namespace`: Namespace of destination PVC
- `-P, --dest-path`: Filesystem path within destination PVC (default: `/`)
- `-d, --dest-delete-extraneous-files`: Delete extraneous files using rsync `--delete`
- `-s, --strategies`: Comma-separated strategies in order (default: `mnt2,svc,lbsvc`)
  - `mnt2`: Mount both PVCs in single pod, local rsync (same namespace only)
  - `svc`: rsync+ssh over ClusterIP Service (same cluster)
  - `lbsvc`: rsync+ssh over LoadBalancer Service (cross-cluster)
  - `local`: Experimental port-forward tunnel (air-gapped clusters)
- `--compress`: Enable rsync compression (default: `true`)
- `-i, --ignore-mounted`: Allow migration while PVC is mounted (use with caution)
- `--helm-set`: Pass custom values to backing Helm chart (images, resources, etc.)

## General Migration and Backup Workflow

### Phase 1: Analysis

1. **Identify PVCs and usage:**
   - `kubectl get pvc -n <namespace>`
   - `kubectl exec -n <namespace> <pod> -- du -sh /mount/path/*`
   - `kubectl exec -n <namespace> <pod> -- ls -la /mount/path/`

2. **Classify data:**
   - **Essential:** Configuration, databases, user data
   - **Regenerable:** Thumbnails, caches, transcoding data
   - **Ephemeral:** Logs, temporary files

3. **Determine action:**
   - Essential → Backup with volsync
   - Regenerable → Skip backup OR separate PVC with different retention
   - Ephemeral → Exclude or use emptyDir

### Phase 2: PVC Reorganization (if needed)

When a PVC contains mixed data (essential + regenerable), split it:

**Commit 1: Preparation:**

- Create new PVC for essential data in `pvc.yaml`
- Scale application to 0 replicas in HelmRelease

**Operations (after push):**

```bash
kubectl pv-migrate \
  --source <mixed-pvc> \
  --source-namespace <namespace> \
  --source-path <essential-subdir> \
  --dest <new-pvc> \
  --dest-namespace <namespace> \
  --strategies mnt2
```

**CRITICAL - Post-Migration Verification:**

After pv-migrate completes, verify two critical aspects before scaling application back up:

1. **Hidden Files:** Subdirectory migration (`--source-path`) may not copy parent directory dotfiles.
   Verify all required hidden files are present.

2. **Ownership:** New PVC root may have incorrect ownership (root:root) even if migrated data is
   correct. Application startup will fail with permission errors.

**Verification command:**

```bash
kubectl run verify --rm -i --image=busybox --overrides='{"spec":{"containers":[{"name":"main",
"image":"busybox","command":["ls","-la","/mnt/"],"volumeMounts":[{"name":"pvc","mountPath":"/mnt"}]}],
"volumes":[{"name":"pvc","persistentVolumeClaim":{"claimName":"<pvc-name>"}}]}}'
```

**Fix ownership if needed:**

```bash
kubectl run fix-perms --rm -i --image=busybox --overrides='{"spec":{"containers":[{"name":"main",
"image":"busybox","command":["sh","-c","chown -R <uid>:<gid> /mnt && ls -la /mnt"],
"volumeMounts":[{"name":"pvc","mountPath":"/mnt"}],"securityContext":{"runAsUser":0}}],
"volumes":[{"name":"pvc","persistentVolumeClaim":{"claimName":"<pvc-name>"}}]}}'
```

Replace `<uid>:<gid>` with application's user (typically `1000:1000`).

**Note:** pv-migrate creates temporary pods to mount both PVCs - no need to pre-mount the
destination PVC in your application.

**Commit 2: Finalization:**

- Add new persistence mount for separated data
- Remove old subPath mount from mixed PVC
- Scale application back to normal replicas

**Post-Migration Cleanup (optional):**

- Source data remains in original PVC after migration
- Manually delete if needed to reclaim space

### Phase 3: Volsync Configuration

**Add to `kustomization.yaml`:**

```yaml
components:
- ../../../components/volsync
```

**Add to `ks.yaml` postBuild.substitute:**

```yaml
postBuild:
  substitute:
    APP: <app-name>
    VOLSYNC_PVC: <pvc-name>
  substituteFrom:
  - kind: Secret
    name: cluster-secrets
```

**Result:** Hourly backups to `s3://volsync-backups/<APP>/` with 24h hourly + 7d daily retention.

## Implementation Examples

### Complex Case: Immich

- **Mixed PVC:** `immich-thumbnails` contained profiles (essential) + thumbnails (regenerable)
- **Action:** Split PVC using pv-migrate
  1. Created `immich-profile` (1Gi) for profiles
  2. Migrated `/profile` subpath from `immich-thumbnails`
  3. Updated mounts to separate concerns
- **Result:** Only profiles backed up, 14Gi thumbnails excluded

## Apps Requiring Backup Configuration

### Default Namespace

#### immich

- **Current PVCs**:
  - `immich-postgres-1` (20Gi, RWO, ceph-block) - Database
  - `immich-thumbnails` (20Gi, RWO, ceph-block) - Generated thumbnails
- **Analysis needed**: Thumbnails are regenerable, evaluate if backup needed
- **Status**: Not started

#### opencloud

- **Current PVC**: `opencloud` (5Gi, RWO, ceph-block)
- **Analysis needed**: Check for cache/logs to exclude
- **Status**: Not started

#### renovate-ce

- **Current PVC**: Unknown (no PVC found in cluster output)
- **Analysis needed**: Verify if PVC exists
- **Status**: Not started

### Media Namespace

#### bazarr

- **Current PVC**: `bazarr` (5Gi, RWO, ceph-block)
- **Analysis needed**: Check for subtitle cache to exclude
- **Status**: Not started

#### imagemaid

- **Current PVC**: `imagemaid` (1Gi, RWO, ceph-block)
- **Analysis needed**: Check what needs backing up
- **Status**: Not started

#### seerr

- **Current PVC**: `seerr` (2Gi, RWO, ceph-block)
- **Status**: Complete (migrated from jellyseerr, volsync component active)

#### kometa

- **Current PVC**: `kometa` (5Gi, RWO, ceph-block)
- **Analysis needed**: Check for cache/generated assets
- **Status**: Not started

#### plex

- **Current PVCs**:
  - `plex-config` (120Gi, RWO, ceph-block) - Main config
  - `plex-cache` (75Gi, RWO, ceph-block) - Cache/transcoding
  - `plex-logs` (5Gi, RWX, ceph-filesystem) - Logs
  - `plex-vector-data` (1Gi, RWO, ceph-block) - Vector sidecar
- **Analysis needed**: Exclude cache/logs/vector, backup config only
- **Status**: Not started

#### prowlarr

- **Current PVC**: `prowlarr` (2Gi, RWO, ceph-block)
- **Analysis needed**: Check for cache to exclude
- **Status**: Not started
- **Note**: volsync PVCs exist but component not in kustomization.yaml

#### qbittorrent

- **Current PVC**: `qbittorrent` (1Gi, RWO, ceph-block)
- **Analysis needed**: Check for cache/incomplete downloads
- **Status**: Not started
- **Note**: volsync PVCs exist but component not in kustomization.yaml

#### sonarr

- **Current PVC**: `sonarr` (5Gi, RWO, ceph-block)
- **Analysis needed**: Check for cache to exclude
- **Status**: Not started

#### sonarr-anime

- **Current PVC**: `sonarr-anime` (5Gi, RWO, ceph-block)
- **Analysis needed**: Check for cache to exclude
- **Status**: Not started

#### tautulli

- **Current PVC**: `tautulli-config` (10Gi, RWO, ceph-block)
- **Analysis needed**: Check for cache/logs to exclude
- **Status**: Not started
- **Note**: volsync PVCs exist but component not in kustomization.yaml

### Home Namespace

#### zwave-js-ui

- **Current PVC**: `zwave-js-ui` (1Gi, RWO, ceph-block)
- **Analysis needed**: Check for cache/logs to exclude
- **Status**: Not started

### Storage Namespace

#### garage

- **Current PVC**: `garage-metadata` (5Gi, RWO, ceph-block)
- **Analysis needed**: Metadata only, S3 data on separate backend
- **Status**: Not started

## Notes

- Some apps (prowlarr, qbittorrent, tautulli) have volsync cache PVCs created but the
  volsync component is not included in their kustomization.yaml
- Need to investigate why these volsync PVCs exist and potentially clean them up
- Apps with multiple PVCs need careful analysis to avoid backing up regenerable data (caches,
  thumbnails, logs)
