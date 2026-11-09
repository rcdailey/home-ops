# VolSync Kopia Root Ownership and UID Mismatch Investigation

- **Date:** 2026-01-31
- **Status:** RESOLVED

## Summary

Kopia mover pods were creating root-owned files (UID 0) on NFS despite having `runAsUser: 1000`
configured in the moverSecurityContext. This caused permission denied errors when subsequent jobs
(running as UID 1000) attempted to read the root-owned files.

**Root Cause:** The `default` namespace had `volsync.backube/privileged-movers: "true"` annotation,
which overrides moverSecurityContext and forces all volsync movers in that namespace to run as root.
This annotation was added for structurizr (which runs as root) but affected ALL apps in the
namespace.

**Resolution:** Removed structurizr application and the privileged-movers annotation from the
default namespace. Fixed existing root-owned files with `chown -R 1000:1000 /mnt/user/volsync`.

## Symptoms

- Files owned by `root:ssh-allow` (UID 0, GID 1000) appearing in `/mnt/user/volsync` on NFS
- Kopia web server logging "permission denied" errors reading index blobs
- Recurring need to run `chown -R 1000:1000 /mnt/user/volsync` on nezuko

## Environment

**VolSync Configuration:**

- Chart: `oci://ghcr.io/home-operations/charts-mirror/volsync-perfectra1n:0.18.2`
- Image: `ghcr.io/rcdailey/volsync:0.17.7-cgo-fix-v2` (custom CGO fix build)
- Controller namespace: `storage`

**NFS Configuration:**

- Server: nezuko (192.168.1.58)
- Export: `/mnt/user/volsync`
- Options: `rw,sec=sys,insecure,no_root_squash`

**Security Context (from moverSecurityContext):**

```yaml
moverSecurityContext:
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  fsGroupChangePolicy: OnRootMismatch
```

## Root Cause Analysis

### The Privileged-Movers Annotation

The `default` namespace kustomization had this patch:

```yaml
patches:
# structurizr runs as root; volsync needs privileged movers to backup root-owned files
- target:
    kind: Namespace
  patch: |
    - op: add
      path: /metadata/annotations/volsync.backube~1privileged-movers
      value: "true"
```

This annotation was added on Jan 28, 2026 to support structurizr, which runs as root and creates
root-owned files that a UID 1000 mover cannot read. The annotation grants `CAP_DAC_OVERRIDE` to
movers, allowing them to read any file regardless of ownership.

**The problem:** This annotation applies namespace-wide, affecting ALL apps in `default`:

- bookstack
- immich
- opencloud
- pocket-id
- structurizr

When the annotation is set, volsync ignores `moverSecurityContext.runAsUser` and runs movers as root
(UID 0). The `fsGroup: 1000` still applied (hence GID 1000 on files), but UID was 0.

### File Timestamp Correlation

Root-owned files were created at exactly 00:00 UTC on Feb 1 (6:00 PM CST Jan 31). The
ReplicationSource lastSyncTime values confirmed which jobs created them:

| ReplicationSource   | lastSyncTime         |
|---------------------|----------------------|
| default/opencloud   | 2026-02-01T00:00:33Z |
| default/immich      | 2026-02-01T00:00:36Z |
| default/structurizr | 2026-02-01T00:00:38Z |
| default/pocket-id   | 2026-02-01T00:00:59Z |
| default/bookstack   | 2026-02-01T00:01:01Z |

Files in `_lo/g_2/` showed the exact pattern:

| Timestamp (UTC)   | UID  | Observation               |
|-------------------|------|---------------------------|
| 00:00:06-00:00:10 | 1000 | Files from storage ns     |
| 00:00:25-00:00:58 | 0    | Files from default ns     |
| 00:01:01+         | 1000 | Correct ownership resumes |

## Investigation Evidence

This section documents all the areas checked during investigation. The privileged-movers annotation
was not initially suspected because the jobs in question were in the `default` namespace, while
initial focus was on `storage` namespace maintenance jobs.

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

**Pattern:** UID 0 (root), GID 1000 (from fsGroup). The fsGroup setting worked, but runAsUser was
overridden by the privileged-movers annotation.

### NFS Export Configuration Verified

```bash
$ ssh nezuko "cat /etc/exports | rg volsync"
"/mnt/user/volsync" -fsid=106,async,no_subtree_check 192.168.1.0/24(rw,sec=sys,insecure,no_root_squash)
```

`no_root_squash` means UID 0 from client is preserved as UID 0 on server. This is NOT the cause; it
just means the NFS server honestly reports what UID created the file.

### Storage Namespace Jobs Verified

Jobs in the `storage` namespace had correct security context and were NOT the source of root files:

```bash
$ kubectl get job kopia-maint-daily-768a081a131cc03c-29498400 -n storage \
    -o jsonpath='{.spec.template.spec.securityContext}'
{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsUser":1000}
```

### Test Jobs in Storage Namespace

Test jobs in the storage namespace (which does NOT have the privileged-movers annotation) worked
correctly:

```bash
$ kubectl apply -f /tmp/test-uid-job.yaml
$ kubectl logs job/test-uid -n storage
=== Process identity ===
uid=1000 gid=1000 groups=1000

=== Creating test file ===
-rw-r--r--. 1 1000 1000 0 Feb  1 01:49 /repository/test-uid-check
```

This confirmed that the volsync image and security context enforcement worked correctly when the
privileged-movers annotation was not present.

### CronJob Template Verified

```bash
$ kubectl get cronjob -n storage -l volsync.backube/kopia-maintenance=true \
    -o jsonpath='{.items[0].spec.jobTemplate.spec.template.spec.securityContext}'
{"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsUser":1000}
```

### ReplicationSource moverSecurityContext Verified

All ReplicationSources had correct moverSecurityContext:

```bash
$ kubectl get replicationsource -n default -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.kopia.moverSecurityContext}{"\n"}{end}'
bookstack   {"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsUser":1000}
immich      {"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsUser":1000}
opencloud   {"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsUser":1000}
pocket-id   {"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsUser":1000}
structurizr {"fsGroup":1000,"fsGroupChangePolicy":"OnRootMismatch","runAsGroup":1000,"runAsUser":1000}
```

This was misleading because the moverSecurityContext was correct; the namespace annotation was
overriding it.

### Default Namespace Annotation (Root Cause)

```bash
$ kubectl get namespace default -o yaml | rg -A 5 "annotations:"
  annotations:
    kustomize.toolkit.fluxcd.io/prune: disabled
    volsync.backube/privileged-movers: "true"
```

The `volsync.backube/privileged-movers: "true"` annotation was the root cause.

### Image Configuration

```bash
$ crane config ghcr.io/rcdailey/volsync:0.17.7-cgo-fix-v2 | jq '.config'
{
  "Env": ["...","USER=volsync"],
  "Entrypoint": ["/bin/bash"],
  ...
}
```

Image has `ENV USER=volsync` (environment variable) but no `USER` directive (Dockerfile
instruction). The image defaults to root, but Kubernetes `runAsUser: 1000` should override this at
runtime, which it does unless privileged-movers is set.

## Ruled Out Causes

| Potential Cause                      | Status    | Evidence                                       |
|--------------------------------------|-----------|------------------------------------------------|
| NFS root_squash misconfiguration     | Ruled out | Export uses no_root_squash; passes UID through |
| Job spec missing security context    | Ruled out | Job spec shows runAsUser: 1000                 |
| CronJob template incorrect           | Ruled out | Template has correct security context          |
| Controller code bug                  | Ruled out | Code review confirms correct implementation    |
| MutatingAdmissionPolicy interference | Ruled out | Test with admission policy works correctly     |
| Volsync controller creating files    | Ruled out | Controller runs as UID 1000                    |
| Image ignoring security context      | Ruled out | Test jobs run correctly as UID 1000            |
| Storage namespace jobs               | Ruled out | Root files came from default namespace         |

## Resolution

1. **Removed structurizr application** - The only app requiring root access
2. **Removed privileged-movers patch** - From `kubernetes/apps/default/kustomization.yaml`
3. **Removed namespace annotation** - `kubectl annotate namespace default
   volsync.backube/privileged-movers-`
4. **Fixed existing files** - `ssh nezuko "chown -R 1000:1000 /mnt/user/volsync"`

**Commit:** `fix(volsync)!: remove structurizr to prevent root-owned backup files`

## Lessons Learned

1. **Namespace-level annotations affect all apps** - The privileged-movers annotation was added for
   one app but affected all apps in the namespace. Apps requiring special permissions should be
   isolated in their own namespace.

2. **moverSecurityContext can be overridden** - The volsync privileged-movers annotation takes
   precedence over moverSecurityContext settings.

3. **Check namespace annotations early** - When security context appears correct but behavior
   differs, check for namespace-level overrides.

4. **File timestamps are valuable forensics** - Correlating file creation times with job execution
   times identified which jobs created the root-owned files.

## Relevant Files

| File                                                    | Purpose                     |
|---------------------------------------------------------|-----------------------------|
| `kubernetes/apps/storage/volsync/helmrelease.yaml`      | Volsync operator config     |
| `kubernetes/apps/storage/volsync/kopiamaintenance.yaml` | KopiaMaintenance CRD config |
| `kubernetes/components/volsync/replicationsource.yaml`  | ReplicationSource template  |
| `kubernetes/apps/default/kustomization.yaml`            | Had privileged-movers patch |

## Commands for Future Reference

```bash
# Check for root-owned files
ssh nezuko "find /mnt/user/volsync -maxdepth 3 -uid 0 -ls 2>/dev/null | head -20"

# Check namespace for privileged-movers annotation
kubectl get namespace <ns> -o jsonpath='{.metadata.annotations.volsync\.backube/privileged-movers}'

# Verify moverSecurityContext
kubectl get replicationsource -n <ns> -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.kopia.moverSecurityContext}{"\n"}{end}'

# Check NFS export options
ssh nezuko "cat /etc/exports"

# Fix permissions
ssh nezuko "chown -R 1000:1000 /mnt/user/volsync"
```
