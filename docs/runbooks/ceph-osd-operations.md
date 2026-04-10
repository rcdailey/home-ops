# Ceph OSD Operations

Manage Ceph OSDs in Rook-managed clusters. Use `hops` for read-only status checks and `kubectl exec`
for mutations:

```bash
# Read-only (use hops)
./scripts/hops.py storage ceph status
./scripts/hops.py storage ceph osd

# Mutations (kubectl exec directly)
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph <command>
```

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
   kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd out {osd-num}
   ```

2. Monitor data migration. Wait until PG count reaches 0 (1-2 hours depending on data size).

   ```bash
   watch -n 10 "kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd df tree | rg 'osd.{osd-num}'"
   kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph status
   ```

3. Verify safe to destroy. Do not proceed until this returns success.

   ```bash
   kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd safe-to-destroy osd.{osd-num}
   ```

4. Remove OSD from cluster.

   ```bash
   kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd down {osd-num}
   kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd crush remove osd.{osd-num}
   kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph auth del osd.{osd-num}
   kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd rm {osd-num}
   ```

5. Update configuration. Remove `devicePathFilter` entry from
   `kubernetes/apps/rook-ceph/cluster/helmrelease.yaml`:

   ```bash
   pre-commit run --files kubernetes/apps/rook-ceph/cluster/helmrelease.yaml
   git add kubernetes/apps/rook-ceph/cluster/helmrelease.yaml
   git commit -m "chore(rook-ceph): remove OSD.{osd-num} from cluster"
   git push
   ```

6. Verify removal.

   ```bash
   kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd tree
   kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph status
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
   pre-commit run --files kubernetes/apps/rook-ceph/cluster/helmrelease.yaml
   git add kubernetes/apps/rook-ceph/cluster/helmrelease.yaml
   git commit -m "feat(rook-ceph): add OSD on {node-hostname}"
   git push
   just reconcile
   ```

3. Monitor OSD creation. OSD creation takes 5-10 minutes.

   ```bash
   kubectl get pods -n rook-ceph -w | rg osd
   kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd tree
   ```

4. Monitor rebalancing. Rebalancing takes 2-4 hours depending on cluster size.

   ```bash
   watch -n 5 "kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph status"
   kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd df tree
   ```

## Common Commands

```bash
# Cluster status
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph status

# List OSDs
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd tree

# OSD utilization
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd df tree

# PG status
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph pg stat
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph pg dump | rg active+clean | wc -l

# Watch cluster
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph -w
```

## Troubleshooting

### OSD Won't Drain

Check for stuck PGs or full OSDs:

```bash
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph pg dump | rg -v active+clean
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd df
```

### OSD Won't Start

Check logs:

```bash
kubectl logs -n rook-ceph -l app=rook-ceph-osd --tail=100
kubectl logs -n rook-ceph -l app=rook-ceph-operator --tail=100
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph device ls
```

### Rebalancing Too Slow

Temporarily increase concurrent backfills:

```bash
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph tell osd.* injectargs '--osd-max-backfills 2'
```

Reset to default after rebalancing:

```bash
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph tell osd.* injectargs '--osd-max-backfills 1'
```

## References

- [Ceph OSD Management][ceph-osd-docs]
- [Ceph CRUSH Map Operations][ceph-crush-docs]
- [Rook Ceph Documentation][rook-docs]

[ceph-osd-docs]: https://github.com/ceph/ceph/blob/main/doc/rados/operations/add-or-rm-osds.rst
[ceph-crush-docs]: https://github.com/ceph/ceph/blob/main/doc/rados/operations/crush-map.rst
[rook-docs]: https://rook.io/docs/rook/latest-release/
