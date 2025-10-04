# VolSync Kopia S3 Prefix Research - Complete Investigation

**Date:** 2025-10-04 **Status:** RESOLVED - Using shared repository pattern **Issue:** Initial
attempts at per-app S3 prefix isolation failed due to trailing slash handling

## Executive Summary

Initial configuration attempts for VolSync Kopia backups using per-app S3 prefixes failed due to
trailing slash stripping behavior in VolSync's entry.sh script. After multiple configuration
attempts and community discussion, resolved by adopting the **shared repository pattern** - the
recommended approach where all apps write to a single Kopia repository with isolation handled via
username@hostname snapshots.

## Current Solution (Shared Repository Pattern)

**Configuration:**

```yaml
KOPIA_REPOSITORY: s3://volsync-backups/
KOPIA_PASSWORD: volsync-shared-kopia-password  # Same for ALL apps
```

**How it works:**

- All apps write to single S3 bucket/repository: `s3://volsync-backups/`
- VolSync automatically sets Kopia username/hostname from namespace/app name
- Snapshots identified as: `prowlarr@media:/data`, `radarr@media:/data`, etc.
- Deduplication works across all apps sharing the repository
- All apps MUST use identical `KOPIA_PASSWORD` (repository-level authentication)

**Benefits:**

- Deduplication across all applications
- Single bucket management
- Works reliably with current VolSync implementation
- Recommended by VolSync Kopia maintainer

## Evidence Chain

### 1. S3 Bucket State

**During failed attempts (using per-app prefixes):**

```txt
volsync-backups/
├── bookstackkopia.blobcfg
├── bookstackkopia.repository
├── radarr-anime_log_20251004224655_4991_...
├── radarr-animekopia.blobcfg
├── radarr-animekopia.repository
├── recyclarrkopia.blobcfg
├── recyclarrkopia.repository
├── sabnzbd_log_20251004224705_376a_...
├── sabnzbdkopia.blobcfg
├── sabnzbdkopia.repository
└── (4,940+ files before cleanup)
```

**Problem:** All repositories colliding in bucket root with object name prefixes.

**Current state (using shared repository):**

```txt
volsync-backups/
├── kopia.repository          # Single shared repository
├── kopia.blobcfg
├── _log_*                    # Kopia log files
├── p*, q*, x*                # Content-addressable data blobs (deduplicated)
└── (snapshots isolated by username@hostname)
```

**Benefit:** Single repository with snapshot-level isolation, deduplication across all apps.

### 2. Official Kopia Documentation

**Source:** <https://kopia.io/docs/reference/command-line/common/repository-create-s3/>

> `--prefix` | Prefix to use for objects in the bucket. **Put trailing slash (/) if you want to use
> prefix as directory.** e.g my-backup-dir/ would put repository contents inside my-backup-dir
> directory

**Also confirmed in:**

- <https://kopia.io/docs/reference/command-line/common/repository-connect-s3/>
- <https://kopia.io/docs/reference/command-line/common/repository-sync-to-s3/>

**Key Behavior:**

- **WITH trailing slash (`my-backup-dir/`):** Creates directory prefix →
  `my-backup-dir/kopia.repository`
- **WITHOUT trailing slash (`my-backup-dir`):** Creates object name prefix →
  `my-backup-dirkopia.repository`

### 3. VolSync Entry.sh Code Analysis

**Location:** `mover-kopia/entry.sh` in perfectra1n/volsync

**Current (incorrect) implementation:**

```bash
# Lines 1249-1254 and 1555-1560
# Remove trailing slash from S3 prefix for consistency
# Kopia handles S3 paths correctly without trailing slashes
if [[ -n "${S3_PREFIX}" ]] && [[ "${S3_PREFIX}" =~ /$ ]]; then
    S3_PREFIX="${S3_PREFIX%/}"
    echo "Removed trailing slash from S3 prefix for consistency"
fi
```

**Pod logs confirm this behavior:**

```txt
Extracted S3 bucket from repository URL: volsync-backups
Resolved S3_ENDPOINT: 192.168.1.58:3900
Removed trailing slash from S3 prefix for consistency
Using S3 prefix: prowlarr
```

### 4. Git History - The Bug Introduction

**Commit:** `09ef3a7` (August 8, 2025) **Title:** "fix(kopia): trailing slash fun" **URL:**
<https://github.com/perfectra1n/volsync/commit/09ef3a7>

**Original (CORRECT) code:**

```bash
# Ensure S3 prefix has a trailing slash for proper path separation
# This prevents ambiguous file paths in S3 storage
if [[ -n "${S3_PREFIX}" ]] && [[ ! "${S3_PREFIX}" =~ /$ ]]; then
    S3_PREFIX="${S3_PREFIX}/"
    echo "Added trailing slash to S3 prefix for proper path separation"
fi
```

**Changed to (INCORRECT):**

```bash
# Remove trailing slash from S3 prefix for consistency
# Kopia handles S3 paths correctly without trailing slashes
if [[ -n "${S3_PREFIX}" ]] && [[ "${S3_PREFIX}" =~ /$ ]]; then
    S3_PREFIX="${S3_PREFIX%/}"
    echo "Removed trailing slash from S3 prefix for consistency"
fi
```

**Analysis:** The change from adding trailing slashes to removing them conflicts with official Kopia
documentation regarding S3 prefix behavior.

## Configuration Attempts Timeline

### Attempt 1 (Sept 29, 21:47)

**Config:**

```yaml
KOPIA_S3_BUCKET: volsync-backups
KOPIA_S3_PREFIX: ${APP}/
```

**Result:** FAILED - entry.sh uses `KOPIA_REPOSITORY` exclusively when present, completely ignores
`KOPIA_S3_PREFIX`

**Observation:** Pod logs showed "No S3 prefix detected in KOPIA_REPOSITORY". Bucket contained only
256 log files, no app directories created.

### Attempt 2 (Oct 1)

**Config:**

```yaml
KOPIA_REPOSITORY: s3://volsync-backups/${APP}/
```

**Result:** FAILED - entry.sh strips trailing slash from URL-embedded prefix

**Impact:** Created 4,940+ flat files in bucket root before cleanup. Files like
`radarr-animekopia.repository` instead of `radarr-anime/kopia.repository`.

**Root cause:** VolSync's entry.sh contains code that strips trailing slashes with comment "Removed
trailing slash from S3 prefix for consistency"

### Attempt 3 (Oct 4)

**Config:**

```yaml
KOPIA_REPOSITORY: s3://volsync-backups/${APP}/
# Removed KOPIA_S3_BUCKET entirely - rely on URL parsing
```

**Result:** FAILED - entry.sh uses app name as object prefix (e.g., `prowlarrkopia.repository`)

**Analysis:** Without `KOPIA_S3_BUCKET` provided separately, entry.sh couldn't parse URL correctly
to extract prefix

### Attempt 4 (Oct 4)

**Config:**

```yaml
KOPIA_REPOSITORY: s3://volsync-backups/${APP}/
KOPIA_S3_BUCKET: volsync-backups  # Added back to help URL parsing
```

**Result:** FAILED - entry.sh explicitly strips trailing slashes from extracted prefix

**Pod logs:**

```txt
Extracted S3 bucket from repository URL: volsync-backups
Resolved S3_ENDPOINT: 192.168.1.58:3900
Removed trailing slash from S3 prefix for consistency
Using S3 prefix: prowlarr
```

**Analysis:** This is hardcoded behavior in VolSync's entry.sh - cannot be worked around with
configuration

### Attempt 5 (Oct 4) - Shared Repository Pattern (SUCCESS)

**Config:**

```yaml
KOPIA_REPOSITORY: s3://volsync-backups/
KOPIA_PASSWORD: volsync-shared-kopia-password  # Same for ALL apps
```

**Result:** SUCCESS - All apps writing to shared repository with snapshot-level isolation

**Key insights:**

- First app (prowlarr) succeeded with unique password
- Second app (radarr-anime) failed with "invalid repository password"
- Root cause: Each app had unique password (e.g., `prowlarr-volsync-backup-password`)
- Solution: Changed all apps to shared password (`volsync-shared-kopia-password`)
- VolSync automatically sets Kopia username/hostname from namespace/app metadata

## Current Implementation

**File:** `kubernetes/components/volsync/secret.yaml`

```yaml
# Kopia repository password - MUST BE SAME for all apps sharing repository
KOPIA_PASSWORD: volsync-shared-kopia-password

# S3 configuration
KOPIA_REPOSITORY: s3://volsync-backups/
KOPIA_S3_ENDPOINT: ${S3_ENDPOINT}
KOPIA_S3_DISABLE_TLS: "true"
```

**How VolSync handles isolation:**

- Automatically sets `KOPIA_OVERRIDE_USERNAME` to app name (e.g., `prowlarr`)
- Automatically sets `KOPIA_OVERRIDE_HOSTNAME` to namespace name (e.g., `media`)
- Kopia creates snapshots as: `prowlarr@media:/data`, `radarr@media:/data`, etc.
- Deduplication works across all snapshots in shared repository

**Benefits:**

- Content deduplication across all apps (e.g., common dependencies, similar files)
- Single bucket/repository management
- Works reliably with current VolSync implementation
- Recommended approach by VolSync Kopia maintainer

**Trade-offs:**

- All apps must use same repository password
- Cannot use different S3 backends per app
- All apps share retention policies at repository level

## Technical Understanding

### Kopia Repository vs Snapshot Isolation

**Repository Level (S3 bucket/prefix):**

- Each repository is a completely separate Kopia instance
- Requires unique S3 path (bucket or bucket+prefix)
- Cannot share deduplication between repositories
- Configuration: `KOPIA_REPOSITORY` URL

**Snapshot Level (within repository):**

- Multiple snapshots within same repository
- Identified by username@hostname:/path
- Shares deduplication within repository
- Configuration: `KOPIA_OVERRIDE_USERNAME`, `KOPIA_OVERRIDE_HOSTNAME`

**Note:** These are two distinct isolation mechanisms. Repository-level isolation requires unique S3
paths (bucket or prefix), while snapshot-level isolation allows multiple users/hosts to share a
single repository.

### S3 Prefix Behavior

S3 doesn't have true directories - it's a flat object store. The "directory" concept is:

1. **Convention-based:** Using `/` in object keys
2. **Console visualization:** AWS console groups by `/` delimiter
3. **Kopia interpretation:**
   - WITH trailing `/`: Treats as directory → `prefix/kopia.repository`
   - WITHOUT trailing `/`: Treats as name prefix → `prefixkopia.repository`

## Related Issues Found

**perfectra1n/volsync issues searched:**

- No issues reported about S3 prefix isolation
- No issues about trailing slash behavior
- Issue #5: Custom CA (unrelated)
- Issue #9: Username override bug (unrelated)

**backube/volsync status:**

- NO Kopia support in upstream
- PR #1723: perfectra1n's Kopia implementation (OPEN since Aug 6, 2025)
- PR #1721: Earlier Kopia attempt (CLOSED)

## VolSync Fork Details

**Image:** `ghcr.io/perfectra1n/volsync:0.16.8` **Chart:**
`oci://ghcr.io/home-operations/charts-mirror/volsync-perfectra1n:0.17.11` **Repository:**
perfectra1n/volsync (appears to be private or deleted) **Upstream PR:**
<https://github.com/backube/volsync/pull/1723>

**Note:** The home-operations/volsynk repository does NOT contain Kopia code - it's the base VolSync
without Kopia support.

## Community Discussion and Resolution

**Discord Thread:** September 12, 2025 - VolSync community channel

**Key outcomes:**

1. **Trailing slash issue acknowledged** - VolSync maintainer acknowledged that per-app S3 prefix
   isolation should work but currently has issues with `KOPIA_S3_PREFIX` and `KOPIA_S3_BUCKET`
   environment variables

2. **Shared repository pattern confirmed as recommended** - Maintainer confirmed that having all
   apps share one bucket/path is the intended/recommended approach to leverage Kopia's multi-tenancy
   and deduplication capabilities

3. **Fix planned** - Maintainer committed to:
   - Resolve issues with `KOPIA_S3_PREFIX` and `KOPIA_S3_BUCKET` environment variables
   - Create unit tests for per-app prefix scenarios
   - Document deduplication benefits more clearly

4. **Multi-tenancy clarification** - Kopia's multi-tenancy support via username/hostname is unique
   compared to Restic/Rsync, allowing multiple apps to safely share a repository with isolated
   snapshots

**Current recommendation:** Use shared repository pattern with snapshot-level isolation (current
implementation) for optimal deduplication and simplified management.

## Alternative Patterns (Future)

### Per-App S3 Prefix Isolation

**Status:** Currently not working reliably due to trailing slash handling

**When to use (after upstream fix):**

- Need independent repository passwords per app
- Require different S3 backends for different apps
- Want per-app retention policies
- Deduplication across apps not beneficial

**Configuration (once fixed):**

```yaml
KOPIA_REPOSITORY: s3://volsync-backups/${APP}/
# OR
KOPIA_S3_BUCKET: volsync-backups
KOPIA_S3_PREFIX: ${APP}/
```

**Note:** This pattern is valid but sacrifices cross-app deduplication benefits.

### Per-App S3 Buckets

**Status:** Works but not recommended

**Configuration:**

```yaml
KOPIA_REPOSITORY: s3://volsync-${APP}/
```

**Trade-offs:**

- Complete isolation per app
- Requires managing multiple S3 buckets
- No deduplication across apps
- Higher storage costs
- More complex lifecycle management

## Files Modified

- `kubernetes/components/volsync/secret.yaml` - Simplified to shared repository pattern
- `docs/memory-bank/volsync-kopia-s3-prefix-research.md` - This document
- `docs/architecture/backup-strategy.md` - Architecture documentation

## Commands for Investigation

```bash
# Check S3 bucket contents
rclone tree garage:volsync-backups --max-depth 2

# View volsync pod logs
kubectl logs -n media volsync-src-prowlarr-<pod>

# Check replicationsource status
kubectl get replicationsources -A
kubectl describe replicationsource <app> -n <namespace>

# Git history search
gh api 'repos/perfectra1n/volsync/commits?path=mover-kopia/entry.sh&per_page=100' --jq '.[] | "\(.sha[:7]) \(.commit.message)"'
```

## References

- Kopia S3 docs: <https://kopia.io/docs/reference/command-line/common/repository-create-s3/>
- VolSync PR: <https://github.com/backube/volsync/pull/1723>
- Relevant commit: <https://github.com/perfectra1n/volsync/commit/09ef3a7>
