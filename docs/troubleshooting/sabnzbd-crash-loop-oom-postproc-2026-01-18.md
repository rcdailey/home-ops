# SABnzbd Crash Loop - OOM and Post-Processing Failures

**Last Updated:** 2026-01-18

**Status:** ROOT CAUSE IDENTIFIED - ACTIVE INVESTIGATION

## Executive Summary

SABnzbd experiencing recurring crash loops with two distinct failure modes:

1. **OOM kills** during post-processing of large downloads (30GB+ REMUXes)
2. **Liveness probe timeouts** when API becomes unresponsive during file copy operations

**ROOT CAUSE:** Cross-filesystem file moves from emptyDir to NFS require full file copy (not
rename). For large files (50-80GB REMUXes), this operation:

- Consumes significant memory due to sabnzbd's article metadata retention in postproc queue
- Takes 5-10+ minutes, exceeding liveness probe timeout thresholds
- Blocks the web API thread, causing probe failures

**Contributing Factor:** sabnzbd retains full article metadata (`decodetable`) in `finished_files`
during post-processing, causing pickle deserialization to consume excessive memory.

## Technical Root Cause Analysis

### Memory Consumption During Postproc Queue Loading

The `postproc2.sab` file is a Python pickle containing `NzbObject` instances with nested structures:

```txt
NzbObject
  └── finished_files: List[NzbFile]    # Completed files retain full metadata
        └── decodetable: List[Article] # ALL articles still in memory
              └── Article (~500 bytes each with Python overhead)
```

**Memory calculation for 30GB download:**

- ~40,000 articles (30GB / 750KB typical article size)
- Each Article: ~500 bytes with Python object overhead
- Base memory: ~20MB for Article objects alone
- With Python fragmentation + object headers + circular references: **500MB-2GB**

**Additional memory consumers:**

- `__setstate__` creates temporary `files + finished_files` concatenation during unpickle
- `saved_articles` set conversion creates temporary copy
- Article cache configured at 1GB
- Normal sabnzbd operation baseline

### Cross-Filesystem Move Operation

When incomplete downloads are on emptyDir and complete directory is on NFS:

1. Python's `shutil.move()` attempts `os.rename()` first
2. Cross-filesystem rename fails with `OSError`
3. Falls back to `shutil.copy2()` + `os.unlink()`
4. File copy blocks the main thread
5. Web API becomes unresponsive during copy
6. Liveness probe times out after 5 minutes (10 failures x 30s)

### The Crash Loop Cycle

```txt
1. Pod starts
2. Loads postproc2.sab (memory spike from pickle deserialization)
3. Resumes stuck postproc job
4. Creates new _UNPACK_{N} directory on NFS
5. Begins file copy from emptyDir to NFS
6. Either:
   a. OOM kill (memory limit exceeded), OR
   b. Liveness probe timeout (API unresponsive during copy)
7. Container restarts (pod preserved, emptyDir data intact)
8. Repeat from step 1, incrementing N
```

**Evidence:** 290 `_UNPACK_An.Unfinished.Life.*` directories created, consuming 1.8TB disk space.

## Git History - Previous Fix Attempts

| Commit    | Date       | Change                                          | Outcome           |
|-----------|------------|-------------------------------------------------|-------------------|
| `c1bbaeb` | 2026-01-18 | Disable probes entirely                         | Still crashes     |
| `3385dea` | 2026-01-18 | Increase memory to 8Gi, enable liveness         | Probe timeout     |
| `47ebb50` | 2026-01-15 | Increase memory request to prevent OOM          | Insufficient      |
| `3f715a9` | 2026-01-15 | Temporarily disable liveness probe              | OOM still occurs  |
| `d60bdec` | 2026-01-14 | Tune liveness probe for I/O-heavy operations    | Insufficient      |
| `ae9b444` | 2026-01-14 | Simplify health probe configuration             | No improvement    |
| `6e14879` | 2025-11-09 | Use emptyDir for incomplete (prevent probes)    | Created this issue|
| `ca62e18` | 2025-10-07 | Enable SQLite WAL mode, increase memory to 6Gi  | Partial help      |
| `143cec2` | 2025-09-21 | Increase resource limits and probe timeouts     | Insufficient      |

**Key insight:** The switch to emptyDir for incomplete downloads (`6e14879`) solved one problem
(probe failures during NFS downloads) but created this cross-filesystem copy issue.

## GitHub Issues Research

Relevant sabnzbd/sabnzbd issues:

- **#3262:** Heavy I/O on ZFS with large queues causes unresponsiveness. Solution: Increase Article
  Cache to 4GB, enable "Pause on Post Processing", disable "Direct Unpack"
- **#2593:** DirectUnpacker thread can hang indefinitely, blocking all post-processing
- **#2948:** Direct unpack hangs when drive runs out of space
- **#2146:** Web UI becomes completely unresponsive during certain operations
- **#807:** Heavy CPU load during par2 verification makes sabnzbd unresponsive

**Maintainer confirmation:** `/api?mode=version` is the recommended health endpoint. No dedicated
health endpoint exists that monitors internal thread health - API shares web server thread.

## Solution Options

### Option 1: NFS for Incomplete Downloads (Tested - Works)

Move incomplete downloads to NFS so moves become instant renames.

```yaml
persistence:
  incomplete:
    type: nfs
    server: 192.168.1.58
    path: /mnt/user/media/.usenet/incomplete
```

**Pros:**

- Eliminates cross-filesystem copy entirely
- Moves are instant (rename syscall)
- Tested working at 56 MB/s download speed

**Cons:**

- Slower download speeds (~56 MB/s vs local storage)
- More NFS I/O during downloads

### Option 2: Generous Probe Thresholds + sabnzbd Tuning

Keep emptyDir but configure sabnzbd and probes for long operations.

**Probe configuration:**

```yaml
probes:
  liveness: &probes
    enabled: true
    custom: true
    spec:
      httpGet:
        path: /api?mode=version
        port: 8080
      timeoutSeconds: 30
      periodSeconds: 30
      failureThreshold: 20  # 10 minutes total tolerance
  readiness: *probes
```

**sabnzbd.ini settings:**

```ini
article_cache_limit = 4G
pause_on_post_processing = 1
direct_unpack = 0
```

**Pros:**

- Fast local storage for downloads
- Allows large file operations to complete

**Cons:**

- 10+ minute window without health monitoring
- Still requires significant memory for postproc queue
- Doesn't address root cause (memory-heavy pickle)

### Option 3: Both (Recommended for Stability)

Use NFS for incomplete + reasonable probe thresholds.

## Cleanup Procedures

### Clear Stuck Postproc Queue

```bash
# Suspend sabnzbd
flux suspend hr sabnzbd -n media
kubectl scale deployment sabnzbd -n media --replicas=0

# Delete postproc2.sab
kubectl run sab-cleanup --rm -it --restart=Never --image=busybox -n media \
  --overrides='{"spec":{"volumes":[{"name":"config","persistentVolumeClaim":{"claimName":"sabnzbd-config"}}],"containers":[{"name":"cleanup","image":"busybox","command":["rm","-f","/config/admin/postproc2.sab"],"volumeMounts":[{"name":"config","mountPath":"/config"}]}]}}'

# Resume
flux resume hr sabnzbd -n media
```

### Clean Orphaned _UNPACK_ Directories

```bash
kubectl run sab-cleanup --rm -it --restart=Never --image=busybox -n media \
  --overrides='{"spec":{"volumes":[{"name":"media","nfs":{"server":"192.168.1.58","path":"/mnt/user/media"}}],"containers":[{"name":"cleanup","image":"busybox","command":["sh","-c","find /media/.usenet/complete -type d -name \"_UNPACK_*\" -exec rm -rf {} +"],"volumeMounts":[{"name":"media","mountPath":"/media"}]}]}}'
```

### Verify No Stuck Jobs

```bash
kubectl run sab-check --rm -it --restart=Never --image=busybox -n media \
  --overrides='{"spec":{"volumes":[{"name":"config","persistentVolumeClaim":{"claimName":"sabnzbd-config"}}],"containers":[{"name":"check","image":"busybox","command":["ls","-la","/config/admin/"],"volumeMounts":[{"name":"config","mountPath":"/config"}]}]}}'
```

## Investigation Commands

### Check Current State

```bash
# Pod status and restart count
kubectl get pods -n media -l app.kubernetes.io/name=sabnzbd

# Describe pod for events
kubectl describe pod -n media -l app.kubernetes.io/name=sabnzbd | tail -40

# Recent logs
kubectl logs -n media -l app.kubernetes.io/name=sabnzbd --tail=100

# Previous container logs (after crash)
kubectl logs -n media -l app.kubernetes.io/name=sabnzbd --previous --tail=100
```

### Check for OOM Kills

```bash
# Talos dmesg for OOM events
talosctl dmesg -n 192.168.1.63 | rg -i "oom|killed|sabnzbd"

# Get pod's cgroup ID from describe, then match in dmesg
kubectl get pod -n media -l app.kubernetes.io/name=sabnzbd -o jsonpath='{.items[0].metadata.uid}'
```

### Check Postproc Queue Size

```bash
kubectl run sab-check --rm -it --restart=Never --image=busybox -n media \
  --overrides='{"spec":{"volumes":[{"name":"config","persistentVolumeClaim":{"claimName":"sabnzbd-config"}}],"containers":[{"name":"check","image":"busybox","command":["ls","-la","/config/admin/postproc2.sab"],"volumeMounts":[{"name":"config","mountPath":"/config"}]}]}}'
```

**Warning signs:**

- postproc2.sab > 1MB indicates large/multiple stuck jobs
- postproc2.sab > 5MB almost certainly will cause OOM

### Check _UNPACK_ Directory Accumulation

```bash
kubectl run sab-check --rm -it --restart=Never --image=busybox -n media \
  --overrides='{"spec":{"volumes":[{"name":"media","nfs":{"server":"192.168.1.58","path":"/mnt/user/media"}}],"containers":[{"name":"check","image":"busybox","command":["sh","-c","find /media/.usenet/complete -type d -name \"_UNPACK_*\" | wc -l"],"volumeMounts":[{"name":"media","mountPath":"/media"}]}]}}'
```

## Failed Downloads Requiring Re-grab

Downloads that were stuck in the crash loop and need to be re-requested from Radarr/Sonarr:

**movies4k:**

- An.Unfinished.Life.2005.BluRay.1080p.DTS-HD.MA.5.1.AVC.HYBRID.REMUX-FraMeSToR
- Jack.Ryan.Shadow.Recruit.2014.UHD.BluRay.2160p.DTS-HD.MA.7.1.DV.HEVC.REMUX-FraMeSToR
- Pacific.Rim.2013.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.HYBRID.REMUX-FraMeSToR
- The.Sound.of.Music.1965.REPACK2.2160p.UHD.BluRay.Remux.DV.HDR.HEVC.TrueHD.Atmos.7.1-CiNEPHiLES
- Monsters.of.Man.2020.UHD.BluRay.2160p.DTS-HD.MA.7.1.HEVC.REMUX-FraMeSToR
- Predator.Badlands.2025.2160p.iT.WEB-DL.DDPA5.1.HDR10P.DV.HEVC-BYNDR

**movies:**

- Free.Birds.2013.1080p.AMZN.WEB-DL.DDP5.1.H.264-GPRS
- Color.Out.of.Space.2020.1080p.BluRay.DTS.5.1.x264-iFT
- Warcraft.2016.BluRay.1080p.DDP.Atmos.5.1.x264-hallowed
- Serenity.2019.1080p.MA.WEB-DL.DDP5.1.H.264-HHWEB
- Robin.Hood.1973.1080p.DSNP.WEB-DL.H.264.SDR.DDP.5.1.English-HONE

**anime:**

- Mushishi.S01E26

## Upstream Recommendations

Consider filing issues with sabnzbd/sabnzbd:

1. **Memory optimization:** Clear `decodetable` from `finished_files` after download verification.
   Article metadata is only needed during download, not postproc.

2. **Health endpoint:** Add dedicated `/health` endpoint that doesn't share web server thread,
   allowing monitoring even during blocking I/O operations.

3. **Postproc failure handling:** Mark jobs as failed after N consecutive failures instead of
   infinite retry loop.

## Document History

| Date       | Changes                                                                    |
|------------|----------------------------------------------------------------------------|
| 2026-01-18 | Initial investigation, root cause identified, cleanup performed            |
| 2026-01-18 | NFS for incomplete tested and working, user reverted due to speed concerns |
| 2026-01-18 | Second crash loop with different download, liveness probe timeout          |
| 2026-01-18 | GitHub issues research completed, optimal probe config documented          |

## Future Investigation Notes

_Add notes here as troubleshooting continues:_

- [ ] Test Option 2 (generous probes + sabnzbd tuning) with 8Gi memory
- [ ] Monitor download speeds with NFS incomplete to determine if 56 MB/s is acceptable
- [ ] Consider filing upstream issue for decodetable memory optimization
