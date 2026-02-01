# VolSync Kopia Root Ownership and UID Mismatch Investigation

**Date:** 2026-01-31
**Status:** ACTIVE INVESTIGATION - ROOT CAUSE UNCONFIRMED

## Executive Summary

Kopia maintenance jobs and mover pods are creating root-owned files (UID 0) on NFS despite having
`runAsUser: 1000` configured in the pod securityContext. This causes permission denied errors when
subsequent jobs (running as UID 1000) cannot read the root-owned files.

**Symptoms:**

- Files owned by `root:ssh-allow` (UID 0, GID 1000) appearing in `/mnt/user/volsync` on NFS
- KubeJobFailed alerts for `kopia-maint-daily` jobs
- Kopia web server logging "permission denied" errors reading index blobs
- Recurring need to run `chown -R 1000:1000 /mnt/user/volsync` on nezuko

**Confirmed facts:**

- Pod securityContext correctly specifies `runAsUser: 1000`
- Test jobs with identical image and security context run correctly as UID 1000
- Files created by test jobs are correctly owned by 1000:1000
- Root-owned files have GID 1000 (from fsGroup), confirming partial security context application

**Mystery:** Security context is correct, test jobs work, but root-owned files still appear.

## Environment

**VolSync Configuration:**

- Chart: `oci://ghcr.io/home-operations/charts-mirror/volsync-perfectra1n:0.18.2`
- Image: `ghcr.io/rcdailey/volsync:0.17.7-cgo-fix-v2` (custom CGO fix build)
- Controller namespace: `storage`

**NFS Configuration:**

- Server: nezuko (192.168.1.58)
- Export: `/mnt/user/volsync`
- Options: `rw,sec=sys,insecure,no_root_squash`

**Security Context (from KopiaMaintenance CRD):**

```yaml
podSecurityContext:
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  fsGroupChangePolicy: OnRootMismatch
```

## Timeline

| Time (CST)       | Event                                                           |
| ---------------- | --------------------------------------------------------------- |
| Jan 30, 3:21 PM  | Commit f239523d: Added podSecurityContext to KopiaMaintenance   |
| Jan 31, 6:34 AM  | Commit 4cd72e26: Deployed CGO fix image (0.17.7-cgo-fix-v2)     |
| Jan 31, 10:00 AM | Maintenance job with OLD image took 4h47m (deadlock symptoms)   |
| Jan 31, 2:47 PM  | 10:00 AM job finally completed                                  |
| Jan 31, 6:00 PM  | First maintenance job with CGO fix image - FAILED (exit code 1) |
| Jan 31, 6:00 PM  | Root-owned files created at exactly this time                   |
| Feb 1, 1:49 AM   | Test job confirms UID 1000 enforcement works correctly          |

## Investigation Evidence

### Root-Owned Files Found

```bash
$ ssh nezuko "stat /mnt/user/volsync/q56/569/1c87f68a0e256d20a96760e9818-s242db56d01c5d01413d.f"
  File: /mnt/user/volsync/q56/569/1c87f68a0e256d20a96760e9818-s242db56d01c5d01413d.f
  Size: 4298
Access: (0600/-rw-------)  Uid: (    0/    root)   Gid: ( 1000/ssh-allow)
Access: 2026-01-31 18:00:31.088921045 -0600
Modify: 2026-01-31 18:00:31.089921041 -0600
Change: 2026-01-31 18:00:31.090921037 -0600
```

**Pattern:** UID 0 (root), GID 1000 (from fsGroup). The fsGroup setting worked, but runAsUser didn't.

### NFS Export Configuration Verified

```bash
$ ssh nezuko "cat /etc/exports | rg volsync"
"/mnt/user/volsync" -fsid=106,async,no_subtree_check 192.168.1.0/24(rw,sec=sys,insecure,no_root_squash)
```

`no_root_squash` means UID 0 from client is preserved as UID 0 on server. This is NOT the cause;
it just means the NFS server honestly reports what UID created the file.

### Job Security Context Verified

```bash
$ kubectl get job kopia-maint-daily-768a081a131cc03c-29498400 -n storage \
    -o jsonpath='{.spec.template.spec.securityContext}'
{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsUser":1000}
```

The failed job's spec correctly shows `runAsUser: 1000`.

### Test Job Results

#### Test 1: Basic image test (no admission policy)

```bash
$ kubectl apply -f /tmp/test-uid-job.yaml
$ kubectl logs job/test-uid -n storage
=== Process identity ===
uid=1000 gid=1000 groups=1000

=== Creating test file ===
-rw-r--r--. 1 1000 1000 0 Feb  1 01:49 /repository/test-uid-check
```

#### Test 2: With MutatingAdmissionPolicy (NFS volume injection)

```bash
$ kubectl apply -f /tmp/test-uid-with-admission.yaml
$ kubectl logs job/kopia-maint-test-uid -n storage
=== Process identity ===
uid=1000 gid=1000 groups=1000

=== Creating test file ===
-rw-r--r--. 1 1000 1000 0 Feb  1 02:01 /repository/test-uid-admission-check
```

Both tests prove the security context IS enforced correctly.

### CronJob Template Verified

```bash
$ kubectl get cronjob -n storage -l volsync.backube/kopia-maintenance=true \
    -o jsonpath='{.items[0].spec.jobTemplate.spec.template.spec.securityContext}'
{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsUser":1000}
```

### Controller Code Review

Reviewed `internal/controller/kopiamaintenance_controller.go` in perfectra1n/volsync. The code
correctly applies `PodSecurityContext` with `runAsUser: 1000` default when creating both CronJobs
and manual Jobs.

### Image Configuration

```bash
$ crane config ghcr.io/rcdailey/volsync:0.17.7-cgo-fix-v2 | jq '.config'
{
  "Env": ["...","USER=volsync"],
  "Entrypoint": ["/bin/bash"],
  ...
}
```

**Issue identified:** Image has `ENV USER=volsync` (environment variable) but no `USER` directive
(Dockerfile instruction). The image defaults to root, BUT Kubernetes `runAsUser: 1000` should
override this at runtime.

## Ruled Out Causes

| Potential Cause                     | Status     | Evidence                                      |
| ----------------------------------- | ---------- | --------------------------------------------- |
| NFS root_squash misconfiguration    | Ruled out  | Export uses no_root_squash; passes UID through|
| Job spec missing security context   | Ruled out  | Job spec shows runAsUser: 1000                |
| CronJob template incorrect          | Ruled out  | Template has correct security context         |
| Controller code bug                 | Ruled out  | Code review confirms correct implementation   |
| MutatingAdmissionPolicy interference| Ruled out  | Test with admission policy works correctly    |
| Volsync controller creating files   | Ruled out  | Controller runs as UID 1000                   |
| Image ignoring security context     | Ruled out  | Test jobs run correctly as UID 1000           |
| Different job at 6PM                | Ruled out  | Only kopia-maint-daily ran at that time       |

## Unresolved Questions

1. **Why did the 6PM job create root-owned files when security context was correct?**
   - Test jobs with identical configuration work correctly
   - The specific pod from 6PM no longer exists to inspect

2. **Is there a race condition or edge case we haven't reproduced?**
   - All test scenarios pass
   - The failure may be non-deterministic

3. **Could there be clock skew or misleading timestamps?**
   - File timestamps precisely match job execution time
   - Unlikely to be a coincidence

## CGO Fix Experiment Context

This investigation overlaps with an experiment to fix a separate issue: kopia user lookup deadlock.

**Original Problem:** Kopia mover jobs hang indefinitely due to glibc `getpwuid_r()` deadlock when
running as UID 1000 without `/etc/passwd` entry.

**Attempted Fix:** Custom image with `CGO_ENABLED=0` to use pure Go user lookup.

**Changes made to perfectra1n/volsync Dockerfile:**

```dockerfile
# Line 78-79: Added CGO disable
ENV CGO_ENABLED=0

# Line 235: Added USER env var (NOT a USER directive)
ENV USER=volsync
```

**Issue:** `ENV USER=volsync` sets an environment variable, not the container's runtime user. The
image still defaults to root. However, Kubernetes `runAsUser: 1000` should override this.

**See also:** [Gist: volsync-kopia-cgo-user-lookup-deadlock-2026-01-31][gist-cgo]

[gist-cgo]: https://gist.github.com/rcdailey/571f0aab65eac86f82c1581f48a64b8d

## Monitoring Gap

**Critical issue:** Kopia logs are not reaching VictoriaLogs, preventing diagnosis of failures.

**Why logs are missing:**

- Kopia writes to `/cache/logs/cli-logs/kopia-*.log` files, not stdout
- Vector collects from `kubernetes_logs` (stdout/stderr only)
- Pods crash/complete before logs can be scraped
- Short-lived job pods don't persist for log collection

**Required fix:** Configure kopia/volsync to log to stdout, or add Vector file source for kopia logs.

## Logging Architecture

This section provides context for implementing proper kopia log collection.

### Current Log Flow

```txt
┌─────────────────────────────────────────────────────────────────────┐
│ Volsync Mover Pod                                                   │
│                                                                     │
│  entry.sh                                                           │
│  ├── echo/log_info() ──────────────────────► stdout ──► Vector ✓   │
│  ├── log_error() ──────────────────────────► stderr ──► Vector ✓   │
│  │                                                                  │
│  └── kopia snapshot/maintenance                                     │
│      ├── --log-level=info ─────────────────► stdout (minimal) ✓    │
│      └── --file-log-level=info ────────────► /cache/logs/*.log ✗   │
│                                              (NOT collected)        │
└─────────────────────────────────────────────────────────────────────┘
```

The entry.sh wrapper script logs extensively to stdout, but kopia's detailed internal logs go to
files that Vector doesn't collect.

### Logging-Related Files

| File | Purpose |
| ---- | ------- |
| `kubernetes/apps/observability/victoria-logs-single/vector/vector-sources.yaml` | Vector input config |
| `kubernetes/apps/observability/victoria-logs-single/vector/vector-transforms.yaml` | Log parsing/filtering |
| `kubernetes/apps/observability/victoria-logs-single/vector/vector-sinks.yaml` | VictoriaLogs output |
| `mover-kopia/entry.sh` (in perfectra1n/volsync repo) | Mover entrypoint script |

### Entry.sh Log Configuration

The entry.sh script (in perfectra1n/volsync) sets these environment variables:

```bash
# Console log level (stdout) - default: info
export KOPIA_LOG_LEVEL="${KOPIA_LOG_LEVEL:-info}"

# File log level (/cache/logs/) - default: info
export KOPIA_FILE_LOG_LEVEL="${KOPIA_FILE_LOG_LEVEL:-info}"

# Log retention
export KOPIA_LOG_DIR_MAX_FILES="${KOPIA_LOG_DIR_MAX_FILES:-3}"
export KOPIA_LOG_DIR_MAX_AGE="${KOPIA_LOG_DIR_MAX_AGE:-4h}"
```

Kopia is invoked with these flags:

```bash
KOPIA=("kopia"
  "--config-file=${KOPIA_CACHE_DIR}/kopia.config"
  "--log-dir=${KOPIA_CACHE_DIR}/logs"
  "--log-level=${KOPIA_LOG_LEVEL}"
  "--file-log-level=${KOPIA_FILE_LOG_LEVEL}"
  "--log-dir-max-files=${KOPIA_LOG_DIR_MAX_FILES}"
  "--log-dir-max-age=${KOPIA_LOG_DIR_MAX_AGE}"
)
```

### Entry.sh Logging Functions

The script has these logging helpers that write to stdout/stderr:

```bash
log_info() { echo "INFO: $*"; }
log_debug() { [[ "${KOPIA_FILE_LOG_LEVEL}" == "debug" ]] && echo "DEBUG: $*"; }
log_error() { echo "ERROR: $*" >&2; }
log_warn() { echo "WARN: $*"; }
```

The `run_with_progress_output()` function captures kopia's output:

```bash
run_with_progress_output() {
    "$@" 2>&1 | tr '\r' '\n'  # Merges stderr to stdout, converts CR to LF
    return "${PIPESTATUS[0]}"
}
```

### Vector Current Configuration

Vector sources (`vector-sources.yaml`):

```yaml
sources:
  k8s:
    type: kubernetes_logs
    use_apiserver_cache: true
    exclude_paths_glob_patterns:
    - /var/log/pods/rook-ceph_*/**
    - /var/log/pods/kube-system_*/**
    - /var/log/pods/flux-system_*/**
    - /var/log/pods/cert-manager_*/**
```

The `storage` namespace is NOT excluded, so volsync pod stdout/stderr should be collected.

### Options for Fixing Log Collection

#### Option A: Increase kopia console verbosity

Set `KOPIA_LOG_LEVEL=debug` in the volsync helmrelease to get more output on stdout. This would
require adding env vars to the mover pods via the ReplicationSource or KopiaMaintenance CRD.

**Pros:** No Vector changes needed
**Cons:** May be very verbose; requires upstream CRD support for env vars

#### Option B: Add Vector transform for volsync pods

Create a Vector filter/transform specifically for volsync pods to ensure their logs are captured
and properly parsed.

**Pros:** Better log organization
**Cons:** Doesn't capture kopia file logs

#### Option C: Sidecar to tail log files

Add a sidecar container that tails `/cache/logs/*.log` to stdout.

**Pros:** Captures all kopia logs
**Cons:** More complex; requires modifying mover pod specs

#### Option D: Configure kopia to skip file logging

If kopia supports `--log-dir=""` or similar to disable file logging and increase console output,
this would be the cleanest solution.

### Testing Log Collection

```bash
# Check if Vector is collecting from storage namespace
./scripts/query-victorialogs.py --namespace storage --start 1h --limit 10

# Check for any volsync-related logs
./scripts/query-victorialogs.py --start 1h 'volsync OR kopia' --limit 20

# Watch logs from a running volsync pod
kubectl logs -f -n <namespace> volsync-src-<app>-<pod> -c kopia
```

## Relevant Files

| File                                                            | Purpose                           |
| --------------------------------------------------------------- | --------------------------------- |
| `kubernetes/apps/storage/volsync/helmrelease.yaml`              | Volsync operator with CGO fix     |
| `kubernetes/apps/storage/volsync/kopiamaintenance.yaml`         | KopiaMaintenance CRD config       |
| `kubernetes/apps/storage/volsync/mutatingadmissionpolicy.yaml`  | NFS volume injection              |
| `kubernetes/components/volsync/replicationsource.yaml`          | ReplicationSource template        |

## Commands for Investigation

```bash
# Check for root-owned files
ssh nezuko "find /mnt/user/volsync -maxdepth 3 -uid 0 -ls 2>/dev/null | head -20"

# Check file timestamps
ssh nezuko "stat /mnt/user/volsync/q56/569"

# Verify job security context
kubectl get job <job-name> -n storage -o jsonpath='{.spec.template.spec.securityContext}' | jq .

# Verify CronJob template
kubectl get cronjob -n storage -l volsync.backube/kopia-maintenance=true \
  -o jsonpath='{.items[0].spec.jobTemplate.spec.template.spec.securityContext}' | jq .

# Check NFS export options
ssh nezuko "cat /etc/exports"

# Run test job
kubectl apply -f /tmp/test-uid-job.yaml
kubectl wait --for=condition=complete job/test-uid -n storage --timeout=60s
kubectl logs job/test-uid -n storage

# Check UID mapping on nezuko
ssh nezuko "id robert; getent group ssh-allow"
# robert = UID 1000, ssh-allow = GID 1000

# Inspect image user config
crane config ghcr.io/rcdailey/volsync:0.17.7-cgo-fix-v2 | jq '.config.User'
```

## Next Steps

1. **Enable kopia logging to stdout** - Required before further diagnosis
2. **Monitor next maintenance run** - Check for new root-owned files at 2AM/10AM
3. **Fix existing permissions** - `ssh nezuko "chown -R 1000:1000 /mnt/user/volsync"`
4. **Verify CGO fix effectiveness** - Check if maintenance jobs complete without deadlock

## Perplexity Research Summary

Research identified several potential causes for `runAsUser` failing while `fsGroup` works:

- **CRI runtime bugs with device mounts** - Not applicable (no devices)
- **NFS no_root_squash interaction** - Verified not the cause
- **Container runtime race conditions** - Possible but not reproducible
- **MutatingAdmissionPolicy modifications** - Tested and ruled out
- **Volsync privileged-movers annotation** - Not set on storage namespace
- **Talos Linux specific issues** - Possible but not confirmed

See Perplexity response in conversation for full details.

## Document History

| Date       | Changes                                                           |
| ---------- | ----------------------------------------------------------------- |
| 2026-01-31 | Initial investigation, root-owned files discovered                |
| 2026-02-01 | Comprehensive testing, all scenarios pass but mystery remains     |
| 2026-02-01 | Document created to track ongoing investigation                   |
