# VolSync Kopia CGO User Lookup Deadlock

- **Date:** 2026-01-31
- **Status:** RESOLVED

## Summary

Kopia mover jobs hang indefinitely due to a futex deadlock caused by CGO-enabled `user.Current()`
calling glibc's `getpwuid_r()` when UID 1000 has no `/etc/passwd` entry. Fix requires building kopia
with `CGO_ENABLED=0` and setting `ENV USER=volsync` in the Dockerfile. Applied in custom image
`ghcr.io/rcdailey/volsync:0.17.7-cgo-fix-v2`.

## Symptoms

Kopia mover jobs hang indefinitely at "Connecting to filesystem repository" and never complete or
time out. The kopia log shows:

```txt
ERROR kopia/repo Cannot determine current user: user: unknown userid 1000
```

After this error, all 12 threads deadlock on `futex_do_wait`. The process never reaches any
repository I/O.

## Environment

**VolSync Version (affected):** `ghcr.io/perfectra1n/volsync:0.17.7`

**VolSync Version (testing fix):** `ghcr.io/rcdailey/volsync:0.17.7-cgo-fix-v2`

**Repository Backend:** NFS filesystem (not S3)

```yaml
# NFS mount injected via MutatingAdmissionPolicy
nfs:
  server: 192.168.1.58
  path: /mnt/user/volsync
```

**Security Context:** All mover jobs run as UID 1000

```yaml
moverSecurityContext:
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  fsGroupChangePolicy: OnRootMismatch
```

### Relevant Configuration Files

| File                                  | Purpose                               |
| ------------------------------------- | ------------------------------------- |
| [helmrelease.yaml][helmrelease]       | VolSync operator deployment (v0.17.7) |
| [replicationsource.yaml][replsrc]     | ReplicationSource template component  |
| [mutatingadmissionpolicy.yaml][mapol] | NFS volume injection for mover jobs   |
| [kopiamaintenance.yaml][kopiam]       | KopiaMaintenance CRD configuration    |

[helmrelease]:
    https://github.com/rcdailey/home-ops/blob/main/kubernetes/apps/storage/volsync/helmrelease.yaml
[replsrc]:
    https://github.com/rcdailey/home-ops/blob/main/kubernetes/components/volsync/replicationsource.yaml
[mapol]:
    https://github.com/rcdailey/home-ops/blob/main/kubernetes/apps/storage/volsync/mutatingadmissionpolicy.yaml
[kopiam]:
    https://github.com/rcdailey/home-ops/blob/main/kubernetes/apps/storage/volsync/kopiamaintenance.yaml

### Container /etc/passwd

The `ghcr.io/perfectra1n/volsync:0.17.7` container has **no entry for UID 1000**:

```bash
$ kubectl exec -n media volsync-src-recyclarr-8p6x6 -c kopia -- cat /etc/passwd
root:x:0:0:root:/root:/bin/bash
bin:x:1:1:bin:/bin:/sbin/nologin
# ... standard system users ...
nobody:x:65534:65534:Kernel Overflow User:/:/sbin/nologin
# NO ENTRY FOR UID 1000
```

## Root Cause

The deadlock occurs because perfectra1n/volsync builds kopia with `CGO_ENABLED=1`, while official
kopia releases use `CGO_ENABLED=0`.

| Aspect               | Official kopia releases    | perfectra1n/volsync        |
| -------------------- | -------------------------- | -------------------------- |
| CGO_ENABLED          | 0                          | 1                          |
| user.Current() impl  | Pure Go, reads /etc/passwd | glibc getpwuid_r() via NSS |
| Unknown UID behavior | Returns error, continues   | Deadlocks on glibc mutexes |

### The Deadlock Chain

```txt
1. Container starts with runAsUser: 1000
2. /etc/passwd has no entry for UID 1000
3. Kopia calls user.Current() in repo/userhost.go:GetDefaultUserName()
4. With CGO_ENABLED=1, Go uses cgo_lookup_unix.go
5. This calls glibc's getpwuid_r()
6. glibc consults NSS (Name Service Switch)
7. NSS attempts to load dynamic modules (libnss_*.so)
8. Internal glibc locks + Go's multi-threaded runtime = FUTEX DEADLOCK
```

### Why CGO Matters

With `CGO_ENABLED=0`, Go's `user.Current()` uses a pure Go implementation that reads `/etc/passwd`
directly. When the UID isn't found, it returns an error immediately and kopia continues with
"nobody" as the username.

With `CGO_ENABLED=1`, Go's `user.Current()` delegates to glibc's `getpwuid_r()`, which uses NSS. NSS
can attempt to load dynamic modules, and the combination of glibc's internal locking with Go's
multi-threaded runtime can cause a futex deadlock.

### Relevant Code Path

```go
// kopia/repo/userhost.go
func GetDefaultUserName(ctx context.Context) string {
    currentUser, err := user.Current()  // <-- DEADLOCKS HERE WITH CGO
    if err != nil {
        log(ctx).Errorf("Cannot determine current user: %s", err)
        return "nobody"  // Never reached due to deadlock
    }
    // ...
}
```

## Required Fix

Both changes are required in the Dockerfile:

```dockerfile
FROM golang-builder AS kopia-builder
ENV CGO_ENABLED=0
ENV USER=volsync
ARG KOPIA_VERSION="v0.22.3"
# ...
RUN go build -o kopia
```

### Why Both Are Needed

1. **CGO_ENABLED=0**: Prevents the glibc/NSS futex deadlock by using Go's pure implementation
2. **USER=volsync**: Go's pure `user.Current()` requires either CGO or the `$USER` environment
   variable; without both disabled CGO and missing USER, it fails with a different error

With only `CGO_ENABLED=0`:

```txt
ERROR kopia/repo Cannot determine current user: user: Current requires cgo or $USER set in environment
```

The process still hangs because kopia retries with exponential backoff without logging to stdout.

## Alternative Fixes (Not Recommended)

### Option B: Add UID 1000 to /etc/passwd

Add to Dockerfile:

```dockerfile
RUN echo "volsync:x:1000:1000:VolSync User:/home/volsync:/sbin/nologin" >> /etc/passwd && \
    echo "volsync:x:1000:" >> /etc/group
```

This would work but couples the image to a specific UID.

### Option C: Configure NSS to Use Files Only

Add to Dockerfile:

```dockerfile
RUN echo "passwd: files" > /etc/nsswitch.conf && \
    echo "group: files" >> /etc/nsswitch.conf
```

This prevents NSS from attempting to load dynamic modules but still relies on CGO.

## Evidence

### Process State Shows Futex Deadlock

```bash
$ kubectl exec -n media volsync-src-recyclarr-8p6x6 -c kopia -- cat /proc/447/wchan
futex_do_wait

$ kubectl exec -n media volsync-src-recyclarr-8p6x6 -c kopia -- cat /proc/447/status | grep Threads
Threads: 12
```

All 12 threads blocked on futex (internal mutex wait).

### No File Descriptors to Repository

```bash
$ kubectl exec -n media volsync-src-recyclarr-8p6x6 -c kopia -- ls -la /proc/447/fd/
lrwx------ 1 1000 1000 64 Jan 31 16:19 0 -> /dev/null
l-wx------ 1 1000 1000 64 Jan 31 16:19 1 -> pipe:[9433711]
l-wx------ 1 1000 1000 64 Jan 31 16:19 2 -> pipe:[9433711]
lr-x------ 1 1000 1000 64 Jan 31 16:19 3 -> /sys/fs/cgroup/cpu.max
lrwx------ 1 1000 1000 64 Jan 31 16:19 4 -> /cache/logs/cli-logs/kopia-*.log
lrwx------ 1 1000 1000 64 Jan 31 16:19 5 -> anon_inode:[eventpoll]
lrwx------ 1 1000 1000 64 Jan 31 16:19 6 -> anon_inode:[eventfd]
```

No file descriptors to `/repository` (NFS). Kopia deadlocked before reaching any repository I/O.

### NFS is Working Fine

```bash
$ kubectl exec -n media volsync-src-recyclarr-8p6x6 -c kopia -- ls /repository
kopia.blobcfg.f  kopia.maintenance.f  kopia.repository.f  p00  p01  ...
```

NFS responds instantly. The issue is not NFS-related.

## Related Issues and References

- [golang/go#38599][go-38599]: `user.Current()` with CGO returns `UnknownUserIdError` when UID isn't
  in `/etc/passwd`
- [kopia/kopia#2195][kopia-2195]: Ability to set UID and GID for Docker (related permission issues)
- [backube/volsync#320][volsync-320]: Main tracking issue for kopia support (PR #1723 from
  perfectra1n)
- [Red Hat BZ #964358][rhbz-964358]: Documents `getpwuid_r()` can deadlock due to glibc internal
  locking

[go-38599]: https://github.com/golang/go/issues/38599
[kopia-2195]: https://github.com/kopia/kopia/issues/2195
[volsync-320]: https://github.com/backube/volsync/issues/320
[rhbz-964358]: https://bugzilla.redhat.com/show_bug.cgi?id=964358

## Verification Status

**Status:** Observing (48-hour validation period started 2026-01-31)

**Test Image:** `ghcr.io/rcdailey/volsync:0.17.7-cgo-fix-v2`

**Initial Results:** Mover jobs completing successfully after applying both fixes. Multiple sync
cycles observed with normal duration (30-90 seconds vs 45+ minute hangs before fix).

**Validation Criteria:**

- [ ] 48 hours of successful syncs
- [ ] KopiaMaintenance jobs complete without issues
- [ ] No new futex deadlocks in mover pod logs
- [ ] No user lookup errors in kopia logs

**Additional Issues Found During Investigation:**

During debugging, several unrelated issues were discovered and resolved:

1. **Orphaned resources**: Previous stuck pods left VolumeSnapshots and PVCs that blocked new syncs
2. **Stale lock files**: 7,666 lock files in `/repository/_lo/g_2/` caused NFS contention
3. **Root-owned files**: KopiaMaintenance jobs (before podSecurityContext fix) created UID 0 files
   that UID 1000 movers could not read

These were environmental issues unrelated to the CGO fix but masked by the earlier deadlock.
