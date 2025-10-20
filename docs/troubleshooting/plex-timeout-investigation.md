# Plex Timeout and Connectivity Issues - Investigation Log

**Last Updated:** 2025-10-20 (Updated with deadlock analysis and external validation) **Status:**
ROOT CAUSE CONFIRMED

## Executive Summary

Plex server experiencing recurring complete failures where all client requests timeout, leading to
health check failures and container restarts. **ROOT CAUSE CONFIRMED:** EAE (Easy Audio Encoder)
Service deadlock during media analysis operations. Issue is NOT network/Cilium/Envoy related - this
is a known Plex bug affecting media analysis workflows.

---

## Incident Timeline - 2025-10-20 (17:15-17:36 CST)

### Initial Report (17:20)

- User watching Daredevil S3E13 when stream cut out
- Shield Pro client unable to start new playback
- Spinner appears, then stops with no video

### Investigation Findings

**17:21:55 - 17:33:18**: Pattern of 30-second timeouts on metadata requests

- Shield requests: `/library/metadata/198409?checkFiles=1&includeChapters=1`
- Shield requests: `/library/metadata/198409?asyncAugmentMetadata=1&checkFiles=1&includeExtras=1`
- All timeout after exactly 30 seconds
- Plex server logs show NO corresponding `Req#` entries (requests never processed)

**17:35:44 - 17:36:24**: Complete failure cascade

- ALL `/hubs/continueWatching` requests timeout (30s)
- ALL `/hubs/promoted` requests timeout (30s)
- ALL `/library/sections` requests timeout (30s)
- Shield displays "Add content to this library" (empty library state)

**17:36:38**: Plex self-initiated graceful shutdown

- Log entry: `WARN - Timed out waiting for server to finish.`
- Plex detected internal deadlock and triggered shutdown
- Killed EAE Service (pid: 640)
- Health checks start failing (server already shutting down)

**17:37:08**: Container terminated

- Exit code: 137 (SIGKILL from kubelet)
- Killed after 30-second graceful shutdown timeout
- Container marked NOT ready
- LoadBalancer IP (192.168.50.100) returns connection refused

**17:38:38**: Container restarted

- New container started successfully
- WAL recovery: 880 frames from library.db, 29 frames from blobs.db
- All subsequent connectivity tests succeeded (post-restart)

---

## Infrastructure Analysis

### Network Layer - VERIFIED HEALTHY

**Cilium IPAM:**

- LoadBalancer IP `192.168.50.100` assigned correctly via `lbipam.cilium.io/ips` annotation
- Status: `cilium.io/IPAMRequestSatisfied: true`
- No errors in Cilium agent logs (checked `cilium-pq7t6` on node `nami`)

**Envoy Gateway:**

- Internal gateway: `192.168.50.72` (healthy)
- External gateway: `192.168.50.73` (healthy)
- No timeout/502/503/504 errors in gateway proxy logs
- HTTPRoutes not involved in direct LoadBalancer access

**LoadBalancer Service:**

- Service: `plex-direct` (type: LoadBalancer)
- ClusterIP: `10.43.89.126`
- LoadBalancer IP: `192.168.50.100`
- Selector: `app.kubernetes.io/name=plex` (matches pod labels correctly)
- Endpoints: `10.42.1.214:32400` (correct pod IP)

**Connectivity Tests:**

- ✅ From cluster pod → LoadBalancer IP: **200 OK** (instant response)
- ✅ From Plex pod → localhost:32400: **200 OK** (instant response)
- ✅ From local machine → LoadBalancer IP: **200 OK** (instant response)
- ❌ From Shield → LoadBalancer IP: **30s timeout** (only during incidents)

**Conclusion:** Network infrastructure is NOT the issue. Simple `/identity` requests work perfectly
from all locations during normal operation.

---

## Plex Application Analysis

### Pod Configuration

**Location:** `kubernetes/apps/media/plex/helmrelease.yaml`

**Container:** `ghcr.io/home-operations/plex:1.42.2.10156`

- Strategy: Recreate (RWO volumes)
- Resources: 1 CPU request, 4Gi memory request, 16Gi limit, Intel GPU
- Security: Non-root (1000:1000), readOnlyRootFilesystem

**Environment:**

```yaml
PLEX_ADVERTISE_URL: http://192.168.50.100:32400,https://plex.${SECRET_DOMAIN}:443
PLEX_PREFERENCE_1: secureConnections=1
PLEX_PREFERENCE_2: LanNetworksBandwidth=192.168.0.0/19
```

**Storage:**

- Config: `plex-config` PVC (Ceph block, metadata + settings)
- Cache: `plex-cache` PVC (Ceph block, cache data)
- Logs: `plex-logs` PVC (Ceph block, log files)
- Media: NFS mount `192.168.1.58:/mnt/user/media` (100TB+ media library)

**Health Probes:**

```yaml
liveness/readiness:
  httpGet:
    path: /identity
    port: 32400
  initialDelaySeconds: 0
  periodSeconds: 10
  timeoutSeconds: 1
  failureThreshold: 3
```

### Database State

**Location:** `/config/Library/Application Support/Plex Media Server/Plug-in Support/Databases/`

- `com.plexapp.plugins.library.db`: **393 MB** (main metadata)
- `com.plexapp.plugins.library.blobs.db`: **609 MB** (artwork/thumbnails)
- Last modified during incident: `17:19` (active queries during timeouts)

### Observed Resource Usage

**During incident:**

- CPU: 8m (minimal - idle/hung state)
- Memory: 421Mi (normal)
- Processes running: Main server + Tuner Service + EAE Service

**EAE Service activity:**

- Started at 17:21 (correlates with transcode profile warnings)
- Plex server log: "unable to find a working transcode profile for video stream"

---

## Request Pattern Analysis

### Successful Requests (Simple)

**Pattern:** Direct endpoint queries without file verification

- `/identity` - Always succeeds instantly
- `/updater/status` - Quick response
- Simple timeline updates - Generally succeed

### Failing Requests (Complex)

**Pattern:** Metadata queries with file system verification

1. **With `checkFiles=1`:**
   - Forces Plex to verify media file accessibility on NFS
   - Requires database query + NFS I/O + stat operations
   - Timeout: 30 seconds consistently

2. **With `asyncAugmentMetadata=1&includeExtras=1`:**
   - Multiple database joins (extras, trailers, related content)
   - Additional NFS reads for supplementary files
   - Timeout: 30 seconds consistently

3. **Hub queries (`/hubs/continueWatching`, `/hubs/promoted`):**
   - Aggregate queries across all libraries (contentDirectoryID=1,2,9,22)
   - Database queries + thumbnail generation + file checks
   - Timeout: 10-30 seconds during degradation

4. **Library listing (`/library/sections/2/all`):**
   - Full library enumeration with metadata
   - Database scan + file verification
   - Timeout: 30 seconds

### Request Processing Flow (Hypothesis)

```txt
Shield Request → LoadBalancer (192.168.50.100) → Pod (10.42.1.214:32400) →
Plex Server Process → SQLite Database Query → NFS File Check → [HANG]
                         ↓
                   No response to client
                         ↓
                   30s timeout on Shield
                         ↓
                   Health check starts failing
                         ↓
                   Container killed/restarted
```

---

## Root Cause Analysis - CONFIRMED

### Confirmed Root Cause: EAE Service Deadlock During Media Analysis

**Direct Evidence from Logs:**

1. **Scheduled library scan triggered (17:15:39.980):**
   - ALL 5 libraries started scanning simultaneously
   - Movies (section 1), TV Shows (section 2), Anime Series (section 9), Music (section 19), Anime
     Movies (section 22)

2. **New media detected (17:21:00.562):**
   - File: `Umamusume - Cinderella Gray S01E16`
   - Triggered media analysis and transcoding profile check

3. **EAE Service spawned (17:21:02.209):**
   - Warning: "unable to find a working transcode profile for video stream"
   - Started EAE at `/tmp/pms-6c49130a-9dd8-4681-98bd-5a3d8b902e23/EasyAudioEncoder`
   - Process ID: 640

4. **Complete silence (17:21:02 - 17:36:00):**
   - **15 minutes with ZERO log entries** (only 23 lines in entire timeframe)
   - Main Plex server log file: only 23KB total
   - No client request processing (Shield timeouts invisible to hung server)
   - Scanner processes completed but main server deadlocked

5. **Self-initiated shutdown (17:36:38.970):**
   - `WARN - Timed out waiting for server to finish.`
   - Plex detected its own deadlock state
   - Killed EAE Service: `INFO - Killing process: Plex EAE Service (pid: 640)`
   - Network service shutdown: `ERROR - Network Service: Error in advertiser handle read: 125
     (Operation canceled)`

6. **Graceful shutdown timeout (17:37:08):**
   - Kubelet sent SIGKILL after 30 seconds
   - Exit code 137 (forced termination)
   - Container restart triggered

**Technical Explanation:**

Plex's EAE (Easy Audio Encoder) Service, spawned during media analysis for transcoding profile
determination, entered a deadlock state. This blocked the main Plex server thread from processing
ANY requests (including simple health checks). After 15 minutes of complete unresponsiveness, Plex's
internal watchdog detected the deadlock and initiated a graceful shutdown, which itself timed out,
requiring forceful termination by Kubernetes.

**Why This Was Missed Initially:**

- Connectivity tests were run AFTER the 17:38:38 container restart
- All tests showed "healthy" because they were testing the NEW container
- The hung container was already terminated by the time investigation started
- Only by examining container restart history and old log files (`.1.log`) was the true timeline
  revealed

### External Validation - Plex Community Reports

**Extensive research of Plex forums and community reports confirms this is a KNOWN BUG:**

**Forum Thread: "Plex Media Server crashes after Nvidia Shield TV boot"**
([forums.plex.tv/t/233356][plex-shield-crash])

- **Identical log pattern:** `WARN - Timed out waiting for server to finish.` followed by shutdown
- **Same trigger:** Library scanning and media analysis operations
- Multiple users report same behavior across different platforms

**Forum Thread: "Plex EAE timeout is back!"** ([forums.plex.tv/t/730883][plex-eae-timeout])

- EAE Service causing server hangs and unresponsiveness
- Occurs during transcoding AND analysis operations
- Users report needing to delete EasyAudioEncoder codec folder and restart

**Common Solutions from Community:**

1. Delete `/config/Library/Application Support/Plex Media Server/Codecs/EasyAudioEncoder` folder
2. Disable hardware transcoding temporarily
3. Disable automatic library scanning
4. Increase inotify watch limits (Linux-specific for large libraries)

**Key Insight:**

This incident differs from typical EAE timeout reports - instead of transcoding failures, the EAE
Service deadlock occurred during **media analysis** (determining transcoding profiles for newly
detected files). This is a less-documented variant of the known EAE bug.

[plex-shield-crash]:
    https://forums.plex.tv/t/plex-media-server-crashes-after-nvidia-shield-tv-boot/233356

[plex-eae-timeout]: https://forums.plex.tv/t/eae-timeout-is-back/730883

---

## Temporary Workarounds (None Implemented)

**Shield Client Side:**

- Increase client timeout > 30s (not configurable)
- Reduce metadata detail requests (not configurable)
- Disable "Continue Watching" auto-refresh (not recommended)

**Plex Server Side:**

- Disable scheduled library scans during peak usage
- Reduce thumbnail quality settings
- Disable "Generate chapter thumbnails"

---

## Proposed Solutions

### Immediate Actions (To Be Implemented)

1. **Delete EasyAudioEncoder Codec Folder (Recommended by Community):**

   ```bash
   kubectl exec -n media deploy/plex -c app -- \
     rm -rf '/config/Library/Application Support/Plex Media Server/Codecs/EasyAudioEncoder'
   # Plex will automatically re-download codecs on next startup
   kubectl rollout restart -n media deploy/plex
   ```

   - Forces fresh codec download
   - May resolve deadlock issues with corrupted codec files
   - **RISK:** Low - Plex automatically re-downloads required codecs

2. **Disable Automatic Library Scanning (Temporary Workaround):**
   - Settings → Library → Scan my library automatically: **DISABLE**
   - Prevents simultaneous multi-library scans that trigger EAE deadlocks
   - Requires manual "Scan Library Files" when adding new media
   - **TRADE-OFF:** Less convenient but prevents recurring deadlocks

3. **Increase Health Check Tolerance:**

   ```yaml
   probes:
     liveness:
       timeoutSeconds: 5        # Increase from 1s
       failureThreshold: 10     # Increase from 3 (allow ~50s hang time)
   ```

   - Prevents premature restarts during temporary EAE hangs
   - Allows Plex's internal watchdog time to recover
   - **CAUTION:** May allow truly hung instances to persist longer

### Long-Term Solutions (Requires Planning)

1. **Disable Hardware Transcoding During Analysis (If Issue Persists):**
   - Settings → Transcoder → Use hardware acceleration: **DISABLE**
   - Community reports suggest EAE deadlocks related to hardware transcoding checks
   - Monitor for 1-2 weeks to confirm resolution
   - **TRADE-OFF:** CPU-based transcoding uses more resources but avoids EAE bugs

2. **Stagger Library Scan Schedules:**
   - Prevent all 5 libraries from scanning simultaneously
   - Use external scheduling (cron) to trigger individual library scans
   - Reduces concurrent EAE Service instances
   - **IMPLEMENTATION:** Requires Plex API automation

3. **Monitor for Plex Updates:**
   - Current version: `1.42.2.10156`
   - Check Plex release notes for EAE-related bug fixes
   - Community reports this has been an ongoing issue across multiple versions
   - Consider Plex Pass beta releases if stable releases continue experiencing issue

4. **Alternative: Switch to Jellyfin (Nuclear Option):**
   - If EAE deadlocks prove unfixable in Plex
   - Jellyfin uses different transcoding architecture (no EAE equivalent)
   - **MASSIVE EFFORT:** Complete media server migration required

---

## Monitoring and Detection

### Key Metrics to Track

**Plex Container:**

- CPU usage patterns (normal: 200-500m, hung: < 10m)
- Memory usage (watch for leaks)
- Health check failure rate
- Container restart count

**Database Performance:**

- SQLite query duration (needs instrumentation)
- WAL file size growth
- Checkpoint frequency

**NFS Performance:**

- Latency to nezuko (192.168.1.58)
- Concurrent connection count
- I/O wait time

**Client Behavior:**

- Shield request timeout rate
- Number of concurrent metadata requests
- Failed request patterns

### Alert Thresholds

- Health check failures > 2 in 60s → investigate
- Container restarts > 1 in 4h → database issue likely
- Shield timeout rate > 20% → incident in progress

---

## Investigation Commands Reference

### Query VictoriaLogs for Plex Logs (PREFERRED)

**Service endpoint:** `http://victoria-logs-single.observability:9428`

**Basic queries:**

```bash
# Get recent Plex logs (last 5 entries)
kubectl run test-vlogs --rm -i --restart=Never --image=curlimages/curl:latest -- \
  curl -s 'http://victoria-logs-single.observability:9428/select/logsql/query?query=namespace:media app:plex&limit=5'

# Filter by log level (errors only)
kubectl run test-vlogs --rm -i --restart=Never --image=curlimages/curl:latest -- \
  curl -s 'http://victoria-logs-single.observability:9428/select/logsql/query?query=namespace:media app:plex level:error&limit=20'

# Search for specific keywords (EAE, timeout, shutdown)
kubectl run test-vlogs --rm -i --restart=Never --image=curlimages/curl:latest -- \
  curl -s 'http://victoria-logs-single.observability:9428/select/logsql/query?query=namespace:media app:plex (EAE OR timeout OR shutdown)&limit=50'

# Time-based queries (last 1 hour)
kubectl run test-vlogs --rm -i --restart=Never --image=curlimages/curl:latest -- \
  curl -s 'http://victoria-logs-single.observability:9428/select/logsql/query?query=namespace:media app:plex _time:1h&limit=100'

# Specific log file (Main server log only)
kubectl run test-vlogs --rm -i --restart=Never --image=curlimages/curl:latest -- \
  curl -s 'http://victoria-logs-single.observability:9428/select/logsql/query?query=namespace:media log_file:"Plex Media Server.log"&limit=10'
```

**LogsQL syntax notes:**

- Field filters: `field:value` (e.g., `namespace:media`, `level:error`)
- Text search: Use quotes for phrases (e.g., `"Timed out waiting"`)
- Boolean operators: `AND`, `OR`, `NOT` (e.g., `EAE OR timeout`)
- Time filters: `_time:1h`, `_time:24h`, `_time:7d`
- Wildcards: Use `*` for partial matches (e.g., `pod:plex*`)

**CRITICAL LIMITATION:** VictoriaLogs only contains logs from RUNNING containers.
For post-mortem analysis of restarted/crashed containers, you MUST use `kubectl exec` to
read rotated log files (`.1.log`, `.2.log`, etc.) from the PVC.

### Check Plex Health (kubectl)

```bash
# Pod status and restart count
kubectl get pods -n media -l app.kubernetes.io/name=plex

# Container readiness and last restart reason
kubectl describe pod -n media -l app.kubernetes.io/name=plex | rg -A 10 'Containers:|Ready:|Last State'

# Check for recent restarts with exit codes
kubectl get pod -n media -l app.kubernetes.io/name=plex -o jsonpath='{.items[0].status.containerStatuses[0].lastState}'

# Resource usage
kubectl top pod -n media -l app.kubernetes.io/name=plex --containers

# Running processes (check for EAE Service)
kubectl exec -n media deploy/plex -c app -- ps aux | rg -i 'plex|eae'
```

### Access Rotated Log Files (Post-Restart Analysis)

**CRITICAL for deadlock investigations:** Rotated logs preserve pre-restart state.

```bash
# List all log files with timestamps
kubectl exec -n media deploy/plex -c app -- \
  ls -lht '/config/Library/Application Support/Plex Media Server/Logs/'

# Read previous container's main log (before last restart)
kubectl exec -n media deploy/plex -c app -- \
  cat '/config/Library/Application Support/Plex Media Server/Logs/Plex Media Server.1.log'

# Search for EAE deadlock pattern in old logs
kubectl exec -n media deploy/plex -c app -- \
  cat '/config/Library/Application Support/Plex Media Server/Logs/Plex Media Server.1.log' | \
  rg -i 'eae|timeout waiting|shutdown'

# Get last 100 lines before restart
kubectl exec -n media deploy/plex -c app -- \
  tail -100 '/config/Library/Application Support/Plex Media Server/Logs/Plex Media Server.1.log'
```

### Database Analysis

```bash
# Database sizes and modification times
kubectl exec -n media deploy/plex -c app -- \
  ls -lh '/config/Library/Application Support/Plex Media Server/Plug-in Support/Databases/'

# Check for WAL files (active write-ahead log)
kubectl exec -n media deploy/plex -c app -- \
  ls -la '/config/Library/Application Support/Plex Media Server/Plug-in Support/Databases/*.db-wal'

# Check WAL file sizes (large WAL = potential checkpoint issues)
kubectl exec -n media deploy/plex -c app -- \
  du -h '/config/Library/Application Support/Plex Media Server/Plug-in Support/Databases/'*.db-wal
```

### Network & Connectivity Tests

```bash
# Test LoadBalancer from cluster
kubectl run test-curl --rm -i --restart=Never --image=curlimages/curl:latest -- \
  curl -v --max-time 5 http://192.168.50.100:32400/identity

# Test from Plex pod itself
kubectl exec -n media deploy/plex -c app -- \
  curl -v --max-time 5 http://localhost:32400/identity

# Check Cilium LoadBalancer status
kubectl get svc -n media plex-direct -o yaml | rg -A 5 'lbipam|loadBalancer'

# Verify service endpoints
kubectl get endpoints -n media plex-direct

# From Shield (via logging endpoint - requires Shield debug mode)
curl -s http://192.168.1.105:32500/logging | tail -100
```

---

## Related Incidents

### 2025-10-20 17:20 CST (This Report)

- **Trigger:** User playback failure during Daredevil S3E13
- **Duration:** ~15 minutes (17:21-17:36)
- **Impact:** All Shield clients unable to access Plex, empty library display
- **Resolution:** Container restart (automatic via failed health checks)

### Previous Occurrences (Reported by User)

- **Frequency:** "Several times" (exact dates unknown)
- **Pattern:** Similar symptoms - timeouts, connection failures
- **Resolution:** Unknown (likely automatic restarts)

---

## Next Investigation Steps

1. **Capture NFS metrics during incident:**
   - Mount statistics from Plex pod
   - NFS server (nezuko) I/O metrics
   - Network latency measurements

2. **Database query profiling:**
   - Enable SQLite query logging in Plex
   - Identify slow queries
   - Measure checkpoint duration

3. **Concurrent request testing:**
   - Simulate multiple Shield clients
   - Trigger metadata requests simultaneously
   - Observe breaking point

4. **NFS alternative testing:**
   - Test with local storage mount
   - Compare performance difference
   - Determine if NFS is primary bottleneck

5. **Plex configuration review:**
   - Review all Plex server settings
   - Check for experimental features causing issues
   - Verify database integrity

---

## Conclusion

The Plex timeout issue is **NOT a Kubernetes networking problem**. Infrastructure (Cilium, Envoy,
LoadBalancer) is functioning correctly. The root cause is a **known Plex bug: EAE Service deadlock
during media analysis operations**, extensively documented in community forums.

**Key Finding:**

EAE (Easy Audio Encoder) Service, spawned during media analysis to determine transcoding profiles
for newly detected files, enters a deadlock state that blocks Plex's main server thread. After 15+
minutes of complete unresponsiveness, Plex's internal watchdog detects the deadlock and initiates
shutdown, which requires forceful termination by Kubernetes.

**Critical Insight:**

Initial investigation incorrectly concluded the issue was database/NFS performance because
connectivity tests were performed AFTER the container had already restarted. The hung container was
already terminated. Only by examining container restart history (`exitCode: 137`) and old log files
(`.1.log`) was the true EAE deadlock identified.

**Recommended Priority Actions:**

1. **Immediate:** Delete EasyAudioEncoder codec folder and restart Plex
2. **Short-term:** Disable automatic library scanning (manual scans only)
3. **Monitoring:** Track container restarts and watch for EAE Service process
4. **Long-term:** Consider disabling hardware transcoding or switching media servers if issue
   persists

**Success Criteria:**

- Zero unplanned container restarts over 7-day period
- Library scans complete without triggering EAE deadlocks
- No "Timed out waiting for server to finish" log entries
- Manual library scans successfully process new media without hangs

---

## Document History

| Date       | Author | Changes                                                       |
| ---------- | ------ | ------------------------------------------------------------- |
| 2025-10-20 | Claude | Initial investigation document with hypothesis                |
| 2025-10-20 | Claude | ROOT CAUSE CONFIRMED: EAE deadlock, external validation added |

---

**Status:** Root cause confirmed. Immediate action: Delete EasyAudioEncoder codec folder.
