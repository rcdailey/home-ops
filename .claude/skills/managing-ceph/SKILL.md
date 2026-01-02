---
name: managing-ceph
description: Runs Ceph commands via rook-ceph-tools for storage inspection and troubleshooting. Use when checking cluster health, pool usage, OSD status, or RBD images.
---

# Managing Ceph Storage

Run `scripts/ceph.sh` with any ceph subcommand.

## Core Commands

```bash
# Cluster health
scripts/ceph.sh status
scripts/ceph.sh health detail

# Storage usage
scripts/ceph.sh df
scripts/ceph.sh df detail
scripts/ceph.sh osd df
scripts/ceph.sh osd df tree

# OSD status
scripts/ceph.sh osd tree

# PG status
scripts/ceph.sh pg stat
scripts/ceph.sh pg dump

# Watch cluster events
scripts/ceph.sh -w

# RBD images
scripts/ceph.sh rbd ls ceph-blockpool
scripts/ceph.sh rbd info ceph-blockpool/<pvc-uuid>

# Device info
scripts/ceph.sh device ls
```

## OSD Operations

### Safety Requirements

Before any OSD removal:

- Cluster must be `HEALTH_OK`
- At least 3 OSDs must remain after removal
- Sufficient capacity to redistribute data

Verify safe-to-destroy before proceeding: `scripts/ceph.sh osd safe-to-destroy osd.{num}`

### Removing an OSD

Key commands in sequence:

1. `osd out {num}` - Mark OSD out, begins data migration
2. Monitor with `osd df tree` until PG count reaches 0 (typically 1-2 hours)
3. `osd safe-to-destroy osd.{num}` - Verify safe before proceeding
4. `osd down {num}` - Mark OSD down
5. `osd crush remove osd.{num}` - Remove from CRUSH map
6. `auth del osd.{num}` - Remove auth keys
7. `osd rm {num}` - Remove OSD

Configuration change: Remove `devicePathFilter` entry from
`kubernetes/apps/rook-ceph/cluster/helmrelease.yaml`.

### Adding an OSD

1. Identify device on target node: `talosctl get disks -n {node-ip}`
2. Add device entry to `kubernetes/apps/rook-ceph/cluster/helmrelease.yaml` under `storage.nodes`
3. OSD creation takes 5-10 minutes; rebalancing takes 2-4 hours

## Troubleshooting

### OSD Won't Drain

Check for stuck PGs: `pg dump | rg -v active+clean`
Check for full OSDs: `osd df`

### OSD Won't Start

Check operator and OSD logs via kubectl in rook-ceph namespace.
Check device status: `device ls`

### Slow Rebalancing

Temporarily increase backfills: `tell osd.* injectargs '--osd-max-backfills 2'`
Reset after rebalancing: `tell osd.* injectargs '--osd-max-backfills 1'`
