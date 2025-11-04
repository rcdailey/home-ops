# Volsync Backup Rollout

Tracking the configuration of volsync backups for apps not currently backed up.

## Apps Requiring Backup Configuration

### Default Namespace

#### authelia
- **Current PVC**: `authelia` (1Gi, RWO, ceph-block)
- **Actual usage**: 400KB (0.04% of allocated 1Gi)
- **Contents**: SQLite database (311KB), configuration files, notifications log
- **Exclusions**: None needed - all data is essential
- **Volsync config**: Backing up entire PVC
- **Status**: Complete

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

#### jellyseerr
- **Current PVC**: `jellyseerr` (2Gi, RWO, ceph-block)
- **Analysis needed**: Check for cache/logs to exclude
- **Status**: Not started
- **Note**: volsync PVCs exist but component not in kustomization.yaml

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

#### otbr
- **Current PVC**: Unknown (no PVC found in cluster output)
- **Analysis needed**: Verify if PVC exists
- **Status**: Not started

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

- Some apps (jellyseerr, prowlarr, qbittorrent, tautulli) have volsync cache PVCs created but the
  volsync component is not included in their kustomization.yaml
- Need to investigate why these volsync PVCs exist and potentially clean them up
- Apps with multiple PVCs need careful analysis to avoid backing up regenerable data (caches,
  thumbnails, logs)
