---
name: managing-ceph
description: Runs Ceph commands via rook-ceph-tools for storage inspection and troubleshooting. Use when checking cluster health, pool usage, OSD status, or RBD images.
---

# Managing Ceph Storage

Run `scripts/ceph.sh` with any ceph subcommand:

```bash
# Cluster health
scripts/ceph.sh status
scripts/ceph.sh health detail

# Storage usage
scripts/ceph.sh df
scripts/ceph.sh df detail
scripts/ceph.sh osd df

# OSD status
scripts/ceph.sh osd tree

# RBD images
scripts/ceph.sh rbd ls ceph-blockpool
scripts/ceph.sh rbd info ceph-blockpool/<pvc-uuid>
```
