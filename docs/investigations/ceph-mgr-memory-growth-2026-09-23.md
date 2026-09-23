# Ceph MGR Linear Memory Growth

- **Date:** 2026-09-23
- **Status:** UNRESOLVED (failover and task-cancel test in progress)

## Summary

The active Ceph manager (`rook-ceph-mgr-a`) grew about 80-90MB per day until it reached 94% of its
2Gi limit and fired `ContainerHighMemory`. The standby stayed flat near 163MB. The leading suspect
is the `rbd_support` module retrying 18 `trash remove` tasks forever; these tasks are a by-design
side effect of VolSync restore snapshots. A test is running: the mgr was failed over and the 18
tasks were cancelled, and the growth rate of the new active mgr is being watched.

## Symptoms

- `ContainerHighMemory` (warning) for container `mgr` in pod `rook-ceph-mgr-a-778854b74-qc7jg` on
  `marin`, firing from 2026-09-23T00:14Z.
- Usage 1923Mi of a 2Gi limit after 17 days of uptime with 0 restarts.
- Ceph `HEALTH_OK` throughout.

## Investigation

### Growth pattern

Daily maximum working set (MB) from `container_memory_working_set_bytes`:

```txt
date        mgr-a (active)  mgr-b (standby)
2026-09-10  924             194
2026-09-12  1057            194
2026-09-14  1250            198
2026-09-16  1437            199
2026-09-17  1526            163
2026-09-18  1530            163
2026-09-20  1661            163
2026-09-22  1838            163
```

- Growth is linear and never releases memory, which points to a leak in the active mgr, not load.
- Growth paused on 2026-09-17 to 2026-09-18, the same day mgr-b dropped from 199MB to 163MB. Cause
  unknown.
- Metric retention starts on 2026-09-06, which is about when mgr-a started. The exact start of the
  growth pattern cannot be determined; backward extrapolation suggests it starts with the process.
- Commit `0e8fe8d9` records an earlier mgr at 97% of a 1Gi limit, so earlier pods likely showed the
  same pattern.

### Process internals

- `dump_mempools` through the admin socket totals about 2.9MB, so the growth is not in Ceph C++
  mempools. This is consistent with Python module memory.
- `heap stats` is not available on the mgr admin socket.

### Enabled modules

```txt
always on: balancer crash devicehealth orchestrator pg_autoscaler progress rbd_support status
           telemetry volumes
enabled:   dashboard iostat nfs prometheus restful
```

- `prometheus` and `dashboard` come from `monitoring.enabled` and `dashboard.enabled` in the
  HelmRelease (present since the initial Rook commit `a76c1e27`).
- `iostat`, `nfs`, and `restful` come from `mgr_initial_modules`, applied once at cluster creation.
- `restful` was removed in Tentacle; `/usr/share/ceph/mgr` in the v20.2.4 image has no `restful`
  directory, so the entry is stale and runs no code.
- No CephNFS resources exist; `iostat` does no background work.

Module cleanup was judged unable to affect the leak.

### Log analysis (1 hour of mgr-a logs)

```txt
1085 [pg_autoscaler INFO
 422 [mgr INFO
 392 [rbd_support INFO
 175 [balancer INFO
 141 [prometheus ERROR   Failed to collect cephadm daemon status: No orchestrator configured
 126 [rbd_support ERROR  [errno 39] RBD image has snapshots (error deleting image from trash)
```

### rbd_support retry loop

- `ceph rbd task list` showed 18 `trash remove` tasks, each with about 4931 `retry_attempts`. At the
  5-minute retry cap, 4931 attempts is about 17 days, which matches the mgr uptime.
- `rbd trash ls -p ceph-blockpool` listed 18 `csi-vol-*` images, deleted between 2025-09-24 and
  2026-08-01.
- Each trashed image holds one snapshot in the `trash` snapshot namespace. That snapshot is the
  parent of a live `csi-snap-*` clone image.
- Each `csi-snap-*` clone backs a VolumeSnapshot owned by a VolSync ReplicationDestination (`*-dst`,
  `copyMethod: Snapshot`). The ReplicationDestination keeps its latest snapshot indefinitely, so the
  parent can never be deleted.

Flow:

1. The ReplicationDestination restores into a temporary destination PVC.
2. VolSync snapshots that PVC; ceph-csi creates a `csi-snap-*` clone of it.
3. VolSync deletes the temporary PVC; ceph-csi moves the image to trash and adds a `trash remove`
   mgr task.
4. The task fails while the clone exists and retries every 5 minutes with no retry limit.

### Upstream research

- ceph-csi design: DeleteVolume always moves the image to trash and adds a `trash remove` task.
  Maintainers state that tasks retrying while clones exist is expected behavior (ceph-csi #3593,
  #3416).
- `rbd_support/task.py`: backoff is 30s times attempt count, capped at 300s. Failed tasks are never
  removed, and no retry limit exists.
- No Ceph, ceph-csi, Rook, or VolSync source links task retries to mgr memory growth.
- The known prometheus module leak (tracker #68989, TTLCache refcounting) is fixed in v20.2.2; the
  cluster runs v20.2.4.

### Reference repositories

- onedr0p/home-ops and buroa/k8s-gitops run the chart-default mgr limit (1Gi) and enable only
  `pg_autoscaler` explicitly, plus dashboard and monitoring.
- aclerici38/home-ops sets a 4Gi mgr limit and disables `restful`, `diskprediction_local`, and
  `rook`.

## Root Cause

Not yet confirmed. Leading hypothesis: each failing `rbd_support` trash-remove retry leaks memory in
the active mgr (about 15KB per retry at about 5,200 retries per day). Secondary suspect: the
prometheus module, which errors on every scrape and has a prior memory history in this cluster.

## Resolution

Test started 2026-09-23 about 22:45Z:

1. `ceph mgr fail a` made mgr-b active. mgr-a restarted in place and dropped to 191Mi.
2. All 18 tasks were cancelled with `ceph rbd task cancel`; `ceph rbd task list` returns 0.

Evaluation after 1-2 days:

- mgr-b stays flat: the retry loop is the cause. Decide how to prevent new tasks from accumulating
  (VolSync ReplicationDestination snapshot handling or periodic task cleanup).
- mgr-b grows 80-90MB per day: the retry loop is ruled out; investigate the prometheus module next.

Side effect: the 18 trashed images no longer delete automatically when their clones are removed.
They require manual `rbd trash rm` after the corresponding VolumeSnapshots are gone. New VolSync
restores will add new tasks.

## References

- [ceph-csi #3593: parent volumes kept in trash by design][csi-3593]
- [ceph-csi #3416: delete snapshots before deleting RBD image][csi-3416]
- [ceph-csi RBD snapshot and clone design][csi-design]
- [Ceph rbd_support task.py][rbd-task]
- [Ceph tracker #68989: ceph-mgr memory leak in prometheus module][tracker-68989]
- Commit `0e8fe8d9`: disabled RBD per-image stats for mgr memory pressure

[csi-3593]: https://github.com/ceph/ceph-csi/issues/3593
[csi-3416]: https://github.com/ceph/ceph-csi/issues/3416
[csi-design]:
    https://github.com/ceph/ceph-csi/blob/809c6c91ee9216f22700dfa755c33126db61c13a/docs/design/proposals/rbd-snap-clone.md
[rbd-task]:
    https://github.com/ceph/ceph/blob/221a920584e4d319d2b66b6f014735db6acc11a5/src/pybind/mgr/rbd_support/task.py
[tracker-68989]: https://tracker.ceph.com/issues/68989
