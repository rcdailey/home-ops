# Ceph OSD Operations

Manage Ceph OSDs in Rook-managed clusters. Use `./scripts/ceph.sh` wrapper for all commands.

## Table of Contents

- [Removing an OSD](#removing-an-osd)
- [Adding an OSD](#adding-an-osd)
- [Common Commands](#common-commands)
- [Troubleshooting](#troubleshooting)
- [References](#references)

## Removing an OSD

Cluster must be `HEALTH_OK` with at least 3 OSDs remaining and sufficient capacity to redistribute
data.

1. Mark OSD out to begin data migration.

   ```bash
   ./scripts/ceph.sh osd out {osd-num}
   ```

2. Monitor data migration. Wait until PG count reaches 0 (1-2 hours depending on data size).

   ```bash
   watch -n 10 "./scripts/ceph.sh osd df tree | rg 'osd.{osd-num}'"
   ./scripts/ceph.sh status
   ```

3. Verify safe to destroy. Do not proceed until this returns success.

   ```bash
   ./scripts/ceph.sh osd safe-to-destroy osd.{osd-num}
   ```

4. Remove OSD from cluster.

   ```bash
   ./scripts/ceph.sh osd down {osd-num}
   ./scripts/ceph.sh osd crush remove osd.{osd-num}
   ./scripts/ceph.sh auth del osd.{osd-num}
   ./scripts/ceph.sh osd rm {osd-num}
   ```

5. Update configuration. Remove `devicePathFilter` entry from
   `kubernetes/apps/rook-ceph/cluster/helmrelease.yaml`:

   ```bash
   ./scripts/test-flux-local.sh
   pre-commit run --files kubernetes/apps/rook-ceph/cluster/helmrelease.yaml
   git add kubernetes/apps/rook-ceph/cluster/helmrelease.yaml
   git commit -m "chore(rook-ceph): remove OSD.{osd-num} from cluster"
   git push
   ```

6. Verify removal.

   ```bash
   ./scripts/ceph.sh osd tree
   ./scripts/ceph.sh status
   ```

## Adding an OSD

1. Identify device. Note the model or serial for `devicePathFilter`.

   ```bash
   talosctl -e {node-ip} -n {node-ip} get disks
   ```

2. Update configuration. Add device entry to `kubernetes/apps/rook-ceph/cluster/helmrelease.yaml`
   under `storage.nodes`:

   ```yaml
   storage:
     nodes:
     - name: "{node-hostname}"
       devicePathFilter: "/dev/disk/by-id/{device-id}"
       config:
         deviceClass: "ssd"
         metadataDevice: ""
         osdsPerDevice: "1"
   ```

   Validate and apply:

   ```bash
   ./scripts/test-flux-local.sh
   pre-commit run --files kubernetes/apps/rook-ceph/cluster/helmrelease.yaml
   git add kubernetes/apps/rook-ceph/cluster/helmrelease.yaml
   git commit -m "feat(rook-ceph): add OSD on {node-hostname}"
   git push
   just reconcile
   ```

3. Monitor OSD creation. OSD creation takes 5-10 minutes.

   ```bash
   kubectl get pods -n rook-ceph -w | rg osd
   ./scripts/ceph.sh osd tree
   ```

4. Monitor rebalancing. Rebalancing takes 2-4 hours depending on cluster size.

   ```bash
   watch -n 5 "./scripts/ceph.sh status"
   ./scripts/ceph.sh osd df tree
   ```

## Common Commands

```bash
# Cluster status
./scripts/ceph.sh status

# List OSDs
./scripts/ceph.sh osd tree

# OSD utilization
./scripts/ceph.sh osd df tree

# PG status
./scripts/ceph.sh pg stat
./scripts/ceph.sh pg dump | rg active+clean | wc -l

# Watch cluster
./scripts/ceph.sh -w
```

## Troubleshooting

### OSD Won't Drain

Check for stuck PGs or full OSDs:

```bash
./scripts/ceph.sh pg dump | rg -v active+clean
./scripts/ceph.sh osd df
```

### OSD Won't Start

Check logs:

```bash
kubectl logs -n rook-ceph -l app=rook-ceph-osd --tail=100
kubectl logs -n rook-ceph -l app=rook-ceph-operator --tail=100
./scripts/ceph.sh device ls
```

### Rebalancing Too Slow

Temporarily increase concurrent backfills:

```bash
./scripts/ceph.sh tell osd.* injectargs '--osd-max-backfills 2'
```

Reset to default after rebalancing:

```bash
./scripts/ceph.sh tell osd.* injectargs '--osd-max-backfills 1'
```

## References

- [Ceph OSD Management][ceph-osd-docs]
- [Ceph CRUSH Map Operations][ceph-crush-docs]
- [Rook Ceph Documentation][rook-docs]

[ceph-osd-docs]: https://github.com/ceph/ceph/blob/main/doc/rados/operations/add-or-rm-osds.rst
[ceph-crush-docs]: https://github.com/ceph/ceph/blob/main/doc/rados/operations/crush-map.rst
[rook-docs]: https://rook.io/docs/rook/latest-release/
