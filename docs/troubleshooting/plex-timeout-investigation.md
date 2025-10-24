# Plex Timeout and Connectivity Issues - Investigation Log

**Last Updated:** 2025-10-22

**Status:** ROOT CAUSE CONFIRMED

## Executive Summary

Plex server experiencing recurring complete failures where all client requests timeout, leading to
health check failures and container restarts.

**ROOT CAUSE CONFIRMED:** Unraid array NFS stale file handle issues causing mount hangs on specific
Kubernetes nodes.

**Secondary Factor:** Plex EAE (Easy Audio Encoder) Service deadlocks during media analysis.

**Primary Issue:** Unraid's SHFS/XFS array filesystem incompatibility with NFS, NOT
network/Cilium/Envoy infrastructure.

## Root Cause: Unraid Array NFS Incompatibility

### Technical Architecture Problem

Unraid's user shares (`/mnt/user/*`) use SHFS (Sharity File System) which aggregates multiple
physical disks (XFS/BTRFS) into unified namespaces. This architecture causes NFS instability:

1. **Inode instability** - Mover operations relocate files between cache and array, changing
   inodes/file handles
2. **NFSv3 protocol limitations** - Poor handling of inode changes and file relocations
3. **Hard link confusion** - SHFS hard link management invalidates NFS client file handle caches
4. **Spindown effects** - Array disk spindown/spinup cycles interrupt NFS connections
5. **Node-specific failures** - Node marin (192.168.1.59) consistently affected, nami/sakura stable

### Why ZFS Pools Solve This

- Bypasses SHFS layer entirely (native ZFS filesystem)
- Stable inode management (no mover operations)
- Proper NFSv4 support with delegations
- 10x performance improvement (1GB/s vs 100-200MB/s)
- No spindown-related disruptions

### Community Validation

**Sources:**

- Unraid forums: "Stale File Handle with NFS (6.12-rc2)" - well-documented NFSv3 + mover issues
- Reddit r/unRAID: "NFS stale file handle. What causes it, and how I fixed it" - Kubernetes + Unraid
  NFS problems
- onedr0p's ":pain:" reaction to "unRAID array NFS" - known issue in homelab community

**Common Solutions:**

1. Migrate to ZFS pools (preferred)
2. Switch to SMB/CIFS (stable but slower)
3. Mount options: `soft,timeo=30,retrans=4` instead of `hard`
4. Disable array spindown
5. Disable NFS hard links support in Unraid settings

**Failed Workarounds:**

- Disabling mover (doesn't help read-only mounts)
- Client-side timeout tuning (masks problem, doesn't solve)
- Mount option changes (minimal improvement)

## Secondary Factor: Plex EAE Service Deadlocks

Plex's EAE (Easy Audio Encoder) Service can enter deadlock states during media analysis, blocking
the main server thread from processing requests.

**Known Plex Bug - Community Reports:**

- Forum: "Plex Media Server crashes after Nvidia Shield TV boot" ([forums.plex.tv/t/233356][1])
  - Identical log pattern: `WARN - Timed out waiting for server to finish.`
  - Same trigger: Library scanning and media analysis operations
- Forum: "Plex EAE timeout is back!" ([forums.plex.tv/t/730883][2])
  - EAE Service causing server hangs during transcoding AND analysis
  - Users report needing to delete EasyAudioEncoder codec folder

**Key Insight:** Initial investigation incorrectly attributed all issues to EAE deadlocks because
connectivity tests were performed AFTER container restarts. Live debugging revealed NFS mount hangs
were the actual blocker.

[1]: https://forums.plex.tv/t/plex-media-server-crashes-after-nvidia-shield-tv-boot/233356
[2]: https://forums.plex.tv/t/eae-timeout-is-back/730883

## Incident History

### 2025-10-22 18:08-18:14 CST - NFS Mount Hang (Primary Root Cause Identified)

- **Trigger:** Desktop Plex client playback attempt (Daredevil S3E13, ratingKey 198409)
- **Duration:** ~6 minutes (transcode decision request never completed)
- **Root Cause:** NFS mount stale/hung on node marin - `/media` mount unresponsive
- **Key Evidence:**
  - Transcode decision requests started but never completed
  - Internal metadata fetch with `checkFiles=1` hung on NFS file verification
  - `timeout 5 stat /media/TV` failed (exit 124) - NFS completely unresponsive
  - `ls /media/TV/` hung indefinitely, required shell kill
  - Pod on node marin (192.168.1.59)
- **Other Nodes Unaffected:**
  - Radarr on node sakura: NFS working (instant `ls /media` response)
  - New Plex pod rescheduled to node nami: NFS working immediately
- **Mitigation:** `kubectl rollout restart -n media deploy/plex`
- **Outcome:** Pod rescheduled to node nami, NFS mount healthy, playback working

### 2025-10-22 17:35 CST - Combined NFS + EAE Issues

- **Trigger:** Desktop Plex client playback attempt (Daredevil metadata request)
- **Duration:** 7+ minutes (17:40:54 - incident ongoing when mitigation applied)
- **Root Cause:** NFS mount hang on node marin (primary), EAE Service residual (secondary)
- **Key Evidence:**
  - Request `#11a5ae` started 17:40:54, never completed
  - No server log activity after request initiation
  - EAE Service PID 355 still running from previous container lifecycle
- **Mitigation:** Deleted EasyAudioEncoder codec folder, restarted Plex deployment
- **Outcome:** Blocked by infrastructure issues (NFS mount timeout, Intel GPU device plugin failure)
- **Additional Findings:**
  - EAE Service persists across library scan disable (not scan-dependent)
  - Deadlock triggered by normal playback metadata requests (not just scans)

### 2025-10-20 17:15-17:36 CST - Initial Incident

- **Trigger:** User playback failure during Daredevil S3E13
- **Duration:** ~15 minutes
- **Symptoms:**
  - Shield Pro client unable to start playback
  - All `/library/metadata` requests timeout (30s)
  - All `/hubs/continueWatching` requests timeout (30s)
  - Shield displays empty library state
- **Resolution:** Container restart (automatic via failed health checks)
- **Initial Hypothesis:** EAE Service deadlock (later revised to NFS primary cause)

## Recommended Solutions

### Priority Actions

1. **Immediate:** Migrate `/mnt/user/media` to Unraid ZFS pool (eliminates SHFS layer)
2. **Alternative:** Switch to SMB/CIFS protocol (more stable with Unraid, ~20% slower)
3. **Workaround:** Add node anti-affinity to prevent Plex scheduling on node marin
4. **Monitoring:** Track NFS mount health per-node, alert on stale file handles
5. **Long-term:** Consider dedicated NAS with native ZFS/NFS support (TrueNAS, etc.)

### Success Criteria

- Zero NFS-related pod restarts over 7-day period
- No `stat` or file access timeouts on `/media` mount
- Consistent performance across all Kubernetes nodes
- No "Stale file handle" errors in system logs

## Node Marin Specific Analysis

Multiple media pods on node marin share same NFS mount (`/mnt/user/media`):

- plex-7bcb8974bc-zwr9l (affected)
- prowlarr-756dd545c-mlwmb
- radarr-4k-7c899546b8-ncw5g
- radarr-anime-84766ccdb4-gbdb6
- sonarr-86c74c66b5-4gcm9

Concentration of concurrent NFS operations may overwhelm mount or trigger kernel NFS client bugs.
Other nodes (nami, sakura, hanekawa) with fewer/different NFS clients remain stable.

## Essential Investigation Commands

### NFS Mount Verification

```bash
# Test NFS mount responsiveness
kubectl exec -n media deploy/plex -c app -- timeout 5 stat /media/TV

# List NFS mount
kubectl exec -n media deploy/plex -c app -- ls /media/TV/

# Check mount statistics
kubectl exec -n media deploy/plex -c app -- cat /proc/mounts | rg media
```

### Plex Health Checks

```bash
# Pod status and restart count
kubectl get pods -n media -l app.kubernetes.io/name=plex

# Container readiness and last restart reason
kubectl describe pod -n media -l app.kubernetes.io/name=plex | rg -A 10 'Containers:|Ready:|Last State'

# Resource usage
kubectl top pod -n media -l app.kubernetes.io/name=plex --containers

# Running processes (check for EAE Service)
kubectl exec -n media deploy/plex -c app -- ps aux | rg -i 'plex|eae'
```

### Post-Restart Analysis

**CRITICAL:** VictoriaLogs only contains logs from running containers. For post-mortem analysis, use
rotated log files from PVC.

```bash
# List all log files with timestamps
kubectl exec -n media deploy/plex -c app -- \
  ls -lht '/config/Library/Application Support/Plex Media Server/Logs/'

# Read previous container's main log (before last restart)
kubectl exec -n media deploy/plex -c app -- \
  cat '/config/Library/Application Support/Plex Media Server/Logs/Plex Media Server.1.log'

# Search for EAE deadlock pattern
kubectl exec -n media deploy/plex -c app -- \
  cat '/config/Library/Application Support/Plex Media Server/Logs/Plex Media Server.1.log' | \
  rg -i 'eae|timeout waiting|shutdown'
```

### VictoriaLogs Queries

```bash
# Recent Plex errors
kubectl run test-vlogs --rm -i --restart=Never --image=curlimages/curl:latest -- \
  curl -s 'http://victoria-logs-single.observability:9428/select/logsql/query?query=namespace:media app:plex level:error&limit=20'

# Search for specific keywords
kubectl run test-vlogs --rm -i --restart=Never --image=curlimages/curl:latest -- \
  curl -s 'http://victoria-logs-single.observability:9428/select/logsql/query?query=namespace:media app:plex (EAE OR timeout OR shutdown)&limit=50'

# Time-based queries (last 1 hour)
kubectl run test-vlogs --rm -i --restart=Never --image=curlimages/curl:latest -- \
  curl -s 'http://victoria-logs-single.observability:9428/select/logsql/query?query=namespace:media app:plex _time:1h&limit=100'
```

## Document History

| Date       | Changes                                                               |
| ---------- | --------------------------------------------------------------------- |
| 2025-10-20 | Initial investigation document with EAE deadlock hypothesis           |
| 2025-10-20 | ROOT CAUSE CONFIRMED: EAE deadlock, external validation added         |
| 2025-10-22 | Deadlock recurrence documented, infrastructure failures identified    |
| 2025-10-22 | ROOT CAUSE REVISED: Unraid NFS primary, EAE secondary, community data |

**Status:** Unraid array NFS incompatibility confirmed as primary root cause. Node marin
consistently affected. Recommended solution: migrate `/mnt/user/media` to ZFS pool or switch to
SMB/CIFS protocol.
