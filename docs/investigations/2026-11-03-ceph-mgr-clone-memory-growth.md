# ceph-mgr memory grows with each CephFS subvolume clone

- **Date:** 2026-11-03
- **Status:** UNRESOLVED

## Summary

The active ceph-mgr grows its resident memory with each CephFS subvolume clone and never releases
it. On this cluster the only daily clone is the Kopiur backup of `home-assistant-rwx`. A workaround
stages that backup from a read-only snapshot, so no clone runs in the mgr. The problem is reported
upstream as [Ceph tracker #82544][tracker]. The requested data is posted and the workaround is back
on; see [Current state](#current-state).

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

| Date   | Clone  | Time (UTC)           | RssAnon before | RssAnon after | Change  |
| ------ | ------ | -------------------- | -------------- | ------------- | ------- |
| Nov 9  | csi    | 07:25:50 to 07:30:42 | 945 MiB        | 1018 MiB      | +73 MiB |
| Nov 9  | manual | 07:32:45 to 07:36:57 | 1018 MiB       | 1030 MiB      | +11 MiB |
| Nov 12 | csi    | 07:25:39 to 07:28:51 | 619 MiB        | 715 MiB       | +96 MiB |
| Nov 12 | manual | 07:30:54 to 07:34:28 | 715 MiB        | 725 MiB       | +10 MiB |
| Nov 13 | csi    | 07:26:05 to 07:29:17 | 719 MiB        | 806 MiB       | +87 MiB |
| Nov 13 | manual | 07:31:20 to 07:34:54 | 806 MiB        | 817 MiB       | +11 MiB |
| Nov 14 | csi    | 07:25:55 to 07:29:07 | 814 MiB        | 894 MiB       | +81 MiB |
| Nov 14 | manual | 07:31:10 to 07:34:44 | 894 MiB        | 906 MiB       | +12 MiB |
| Nov 15 | csi    | 07:25:50 to 07:29:12 | 903 MiB        | 984 MiB       | +81 MiB |
| Nov 15 | manual | 07:31:16 to 07:34:50 | 984 MiB        | 989 MiB       | +5 MiB  |
| Nov 16 | csi    | 07:25:37 to 07:28:48 | 986 MiB        | 1074 MiB      | +88 MiB |
| Nov 16 | manual | 07:30:52 to 07:35:29 | 1074 MiB       | 1090 MiB      | +15 MiB |

The csi "before" capture is at 07:10, about 15 minutes before the clone. `ceph fs clone status` no
longer reports a source after the clone completes, so the script logged `source=null` and recorded
no rbytes or rentries for the csi snapshot.

At 13:23 UTC on Nov 9, the Rook upgrade to v1.21.2 recreated both mgr pods. mgr-a stayed active with
a new PID (3783381) and about 170 MiB RssAnon. Continuity with the earlier samples ended there.

The Talos upgrade was then suspended with the annotation `tuppr.home-operations.com/suspend=true`,
but on Nov 10 it ran anyway and rebooted every node between 09:05 and 09:25 UTC. The annotation was
gone afterwards; why is unknown. mgr-a came back on `nami` while the capture pod stayed pinned to
`hanekawa`, so Nov 10 and 11 recorded no memory data. Commit `f92bf5a2` replaced the pin with pod
affinity to mgr-a. Nov 12 to 16 come from one process (PID 6122), which had already run one csi and
one manual clone on Nov 11.

The first clone of each day adds 73 to 96 MiB; a manual clone right after adds 5 to 15 MiB. In step
1, daily manual clones without a csi clone before them added 71 to 171 MiB, so the growth may depend
on the first clone after an idle period rather than on who issues it. RssAnon stays flat between
runs. This data and `phase2.tar.gz` are tracker note #385816.

## Current state

- Step 2 is complete and posted. Commit `7c8de5ef` restored the workaround, so no clones run.
- The capture app still samples mgr memory every minute; it runs no clones without a csi clone.
- mgr-a keeps its grown memory (1,088 MiB on Nov 16) until it restarts or `ceph mgr fail` runs.

## Resume

1. Watch tracker #82544 for the maintainer's reply.
2. Remove `kubernetes/apps/rook-ceph/mgr-leak-capture/` and its entry in
   `kubernetes/apps/rook-ceph/kustomization.yaml` when the tracker needs no more data.

## Root Cause

Unconfirmed. Each subvolume clone executed by the mgr `volumes` module leaves memory in the mgr's
`[heap]`. The size per clone varies (+5 to +171 MiB) and is not explained yet.

## Resolution

Workaround only, in `2697f379`: stage the home-assistant backup from a read-only snapshot so no
clone runs. Reverted for data collection in `5deb9b5e` and restored in `7c8de5ef`.

## References

- [Ceph tracker #82544][tracker]
- [Ceph tracker #77724 (`remote()` leak)][t77724]
- [Tuppr suspend and resume][tuppr-suspend]

[tracker]: https://tracker.ceph.com/issues/82544
[t77724]: https://tracker.ceph.com/issues/77724
[tuppr-suspend]: https://github.com/home-operations/tuppr/blob/main/docs/operations.md
