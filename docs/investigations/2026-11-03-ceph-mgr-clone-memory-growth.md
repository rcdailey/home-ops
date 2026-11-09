# ceph-mgr memory grows with each CephFS subvolume clone

- **Date:** 2026-11-03
- **Status:** UNRESOLVED

## Summary

The active ceph-mgr grows its resident memory with each CephFS subvolume clone and never releases
it. On this cluster the only daily clone is the Kopiur backup of `home-assistant-rwx`. A workaround
stages that backup from a read-only snapshot, so no clone runs in the mgr. The problem is reported
upstream as [Ceph tracker #82544][tracker], and data collection for the maintainer is in progress.
The workaround is reverted for that data collection; see [Current state](#current-state).

## Symptoms

`ContainerHighMemory` fired for `rook-ceph-mgr-b`. Over 14 days its memory grew from about 300 MiB
to 1.85 GiB, against a 2 GiB limit. The standby mgr stayed at about 194 MiB. Memory rose in steps of
about 89 MiB, one per day, each at the time of the daily `home-assistant-rwx` backup.

Environment: Ceph 20.2.4 (Tentacle), Rook v1.21.0 (v1.21.2 from 2026-11-09), ceph-csi v3.18.1, Talos
v1.14.4, Kubernetes v1.37.1. The Rook mgr module is disabled and no orchestrator backend is set.

## Investigation

### Cause of the daily steps

Kopiur backs up a CephFS PVC by restoring its VolumeSnapshot into a staged PVC. ceph-csi implements
that restore as a full subvolume clone, and the mgr `volumes` module (`async_cloner`) copies every
file inside the mgr process. Ceph mempools held only 2.8 MB and the thread count stayed flat, so the
growth is outside Ceph's accounted C++ allocations.

Known Tentacle mgr leaks (tracker 77633, 78165, 78589, 79492) all need the Rook mgr module, which is
disabled here. No upstream report tied mgr memory to volumes clones, so the issue was filed as
[#82544][tracker].

### Workaround

Commit `2697f379` adds the `ceph-filesystem-snapshot` StorageClass (`backingSnapshot: "true"`) and
patches the home-assistant SnapshotPolicy to stage on it as `ReadOnlyMany`. The staged PVC mounts
the snapshot directly, so no clone runs. On 2026-11-03 the backup made no clone and staging took 53
s. `ceph mgr fail` on 2026-11-02 moved the active mgr from b to a and released the memory.

### Manual clone tests (2026-11-03)

Each test cloned a fresh snapshot of the source subvolume
(`csi-vol-e20b9053-e458-45ac-acb6-f9ed7ce05512`, group `csi`; about 146 MiB, 10,804 entries), then
removed the clone and snapshot. RSS was read 2 minutes after each clone finished.

| Clone              | RSS after              | Change               |
| ------------------ | ---------------------- | -------------------- |
| 1 (`debug_mgr=10`) | 650 MiB                | +345 MiB             |
| 2                  | 666 MiB                | +16 MiB              |
| 3 to 6             | 678, 681, 690, 688 MiB | +11, +3, +10, -2 MiB |

Clone 1 was the first clone on mgr-a since it became active. The copy logs `cptree: (IGNORE)` for
one Unix socket (`.vscode/code-server-ipc.sock`). The reply with this data, a `debug_mgr=10` log and
`perf dump` before and after is note #382024 on the tracker.

### Maintainer's plan

Venky Shankar (tracker note #6) read the large first jump as freed memory retained by tcmalloc, and
the slow drift as #77724 (a `remote()` leak not fixed in 20.2.4). He asked for:

1. ceph-csi clones off; one manual clone every 24 hours for 2-3 days, without failing the mgr.
2. ceph-csi clones on for 2-3 days; after each csi clone, one manual clone as soon as possible.

Capture: VmRSS and RssAnon every minute; `/proc/<pid>/smaps` and `ceph tell mgr.<id> perf dump` just
before and 2 minutes after each clone; clone start and finish times; the snapshot's
`ceph.dir.rbytes` and `ceph.dir.rentries`. Default log level.

### Capture app

Commit `722735ba` adds `kubernetes/apps/rook-ceph/mgr-leak-capture/`, a temporary app-template
Deployment pinned to `hanekawa` (mgr-a's node). It uses `hostPID`, root and `SYS_PTRACE` to read the
mgr's `smaps`. Its script (`config/capture.sh`) writes to the PVC at `/data`:

- `rss.csv`: VmRSS and RssAnon every minute, with the mgr PID.
- `events.log`: daily run times, clone states and snapshot stats.
- `captures/<time>-<label>/`: `smaps.gz`, `perf-dump.json` and `status.txt` per capture.

`MODE: manual` runs one manual clone at `TRIGGER_AT` (UTC). `MODE: csi` captures at `TRIGGER_AT`,
waits for a new subvolume in group `csi`, captures 2 minutes after it completes, then runs one
manual clone.

### Step 1 results (manual clones, mgr-a PID 12853)

| Date  | Clone (UTC)          | rbytes    | RssAnon before | RssAnon +2 min | Change   |
| ----- | -------------------- | --------- | -------------- | -------------- | -------- |
| Nov 6 | 07:25:19 to 07:29:29 | 153971581 | 629 MiB        | 799 MiB        | +171 MiB |
| Nov 7 | 07:25:17 to 07:29:27 | 154125930 | 797 MiB        | 876 MiB        | +79 MiB  |
| Nov 8 | 07:25:13 to 07:29:23 | 154285041 | 874 MiB        | 946 MiB        | +71 MiB  |

RssAnon stayed flat between clones. In `smaps`, almost all growth is in `[heap]` (517 to 821 MiB of
anonymous memory over the three clones). Other anonymous mappings went from 105 to 118 MiB. This
data and the capture files (`phase1.tar.gz`) are tracker note #383873.

### Step 2 (csi clones)

Commit `5deb9b5e` removes the SnapshotPolicy staging patch and sets `MODE: csi`,
`TRIGGER_AT: "07:10"`. The StorageClass from `2697f379` stays.

| Date  | Clone  | Time (UTC)           | RssAnon before | RssAnon after | Change  |
| ----- | ------ | -------------------- | -------------- | ------------- | ------- |
| Nov 9 | csi    | 07:25:50 to 07:30:42 | 945 MiB        | 1018 MiB      | +73 MiB |
| Nov 9 | manual | 07:32:45 to 07:36:57 | 1018 MiB       | 1030 MiB      | +11 MiB |

The csi "before" capture is at 07:10, about 15 minutes before the clone. `ceph fs clone status` no
longer reports a source after the clone completes, so the script logged `source=null` and recorded
no rbytes or rentries for the csi snapshot.

At 13:23 UTC on Nov 9, the Rook upgrade to v1.21.2 recreated both mgr pods. mgr-a stayed active with
a new PID (3783381) and about 170 MiB RssAnon. Continuity with the earlier samples ended there. To
prevent more restarts, the Talos upgrade is suspended with the annotation
`tuppr.home-operations.com/suspend=true` on TalosUpgrade `talos`.

## Current state

- Step 2 continues on the new mgr process for Nov 10 to 12. Nov 10 is the first clone on that
  process and may include a large one-time jump; Nov 11 and 12 are the comparable samples.
- The workaround is off: one ceph-csi clone and one manual clone run each day.
- The Talos upgrade is suspended outside Git.

## Resume

1. After about 07:40 UTC each day, check `/data/events.log`, `/data/captures/` and the tail of
   `/data/rss.csv` in `deploy/mgr-leak-capture` (namespace `rook-ceph`). Confirm one PID in the
   samples since the last check and that `ceph mgr stat` still shows mgr-a active.
2. After the Nov 12 run, copy `/data` out, summarize step 2 and post it to the tracker with the
   files attached.
3. Restore the workaround: revert `5deb9b5e`'s SnapshotPolicy change (re-add the staging patch in
   `kubernetes/apps/home/home-assistant/kustomization.yaml`).
4. Resume the Talos upgrade:
   `kubectl annotate talosupgrade talos tuppr.home-operations.com/suspend-`.
5. Remove `kubernetes/apps/rook-ceph/mgr-leak-capture/` and its entry in
   `kubernetes/apps/rook-ceph/kustomization.yaml` when the tracker needs no more data.

## Root Cause

Unconfirmed. Each subvolume clone executed by the mgr `volumes` module leaves memory in the mgr's
`[heap]`. The size per clone varies (+11 to +171 MiB) and is not explained yet.

## Resolution

Workaround only, in `2697f379`: stage the home-assistant backup from a read-only snapshot so no
clone runs. Temporarily reverted for data collection in `5deb9b5e`.

## References

- [Ceph tracker #82544][tracker]
- [Ceph tracker #77724 (`remote()` leak)][t77724]
- [Tuppr suspend and resume][tuppr-suspend]

[tracker]: https://tracker.ceph.com/issues/82544
[t77724]: https://tracker.ceph.com/issues/77724
[tuppr-suspend]: https://github.com/home-operations/tuppr/blob/main/docs/operations.md
