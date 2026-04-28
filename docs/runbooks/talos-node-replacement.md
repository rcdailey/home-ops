# Talos node replacement

Replace Talos system disks while preserving node identity. Requires a Talos USB installer.

All `just talos` recipes accept node names and resolve IPs from `talos/nodes.yaml`. If you omit the
node name, you get an interactive picker. Run `just talos list-nodes` to see what's available.

## Table of contents

- [Control plane disk replacement](#control-plane-disk-replacement)
- [Worker disk replacement](#worker-disk-replacement)
- [Moving to a different disk](#moving-to-a-different-disk)
- [Additional verification](#additional-verification)
- [Troubleshooting](#troubleshooting)
- [References](#references)

## Control plane disk replacement

Control plane nodes run etcd, which needs a 2-of-3 majority. Do one node at a time and verify full
rejoin before touching the next.

1. Take an etcd snapshot. The recipe checks etcd health first (all members present and responding)
   and fails if anything is wrong.

   ```bash
   just talos etcd-snapshot
   ```

2. Reset the node. This cordons, drains, leaves the etcd cluster, wipes the Talos system disk (sda),
   and shuts down. The Ceph OSD (nvme0n1) is not touched. The recipe checks etcd health before
   proceeding.

   ```bash
   just talos reset-node {node}
   ```

   Wait for the node to fully shut down before continuing.

3. Remove the stale Kubernetes node object.

   ```bash
   just talos remove-node {node}
   ```

4. Physically swap the drive. Insert the Talos USB installer, power on, and boot from USB.

5. Identify the new disk. Record the exact MODEL string. The recipe auto-detects maintenance mode
   and uses `--insecure` automatically.

   ```bash
   just talos get-disks {node}
   ```

6. Update `talos/nodes.yaml` with the new disk model:

   ```yaml
   nodes:
     {node}:
       disk_model: "{NEW_DISK_MODEL}"
   ```

   Remove the `disk_size` field if present (only needed when two disks share the same model prefix).

7. Apply the config. Maintenance mode is auto-detected. The node installs to the new disk and
   reboots automatically. Wait 5-8 minutes for it to rejoin the cluster and re-enter etcd
   membership.

   ```bash
   just talos apply-node {node}
   ```

8. Verify the node is back and etcd has three healthy members again. Don't move on to the next node
   until this looks right.

   ```bash
   just talos verify-node {node}
   ```

Repeat from step 1 for the next control plane node.

## Worker disk replacement

Workers don't run etcd, so no snapshot or etcd verification is needed.

1. Shut down the node.

   ```bash
   just talos shutdown-node {node}
   ```

   Insert the Talos USB installer, power on, and boot from USB.

2. Identify the new disk. Record the exact MODEL string.

   ```bash
   just talos get-disks {node}
   ```

3. Update `talos/nodes.yaml` with the new disk model (see [step 6](#control-plane-disk-replacement)
   for format).

4. Apply the config. The node installs and reboots automatically. Wait 5-8 minutes for it to rejoin.

   ```bash
   just talos apply-node {node}
   ```

5. Verify the node rejoined.

   ```bash
   just talos verify-node {node}
   ```

## Moving to a different disk

When the new disk is already physically installed alongside the old one (e.g., migrating SATA to
NVMe).

Follow the [control plane](#control-plane-disk-replacement) or [worker](#worker-disk-replacement)
procedure as appropriate. Both disks are visible during disk identification. Make sure `disk_model`
in `talos/nodes.yaml` targets the new disk. The old disk stays untouched after installation.

## Additional verification

If something feels off after a swap, these can help narrow it down:

```bash
# View system disk
talosctl get systemdisk -n {node-ip}

# Check mounts
talosctl get mounts -n {node-ip}

# View services
talosctl services -n {node-ip}

# Check logs
talosctl dmesg -n {node-ip}
```

Node IPs are in `talos/nodes.yaml` (or run `just talos list-nodes`).

## Troubleshooting

### Node won't boot

Check physical connections, BIOS boot order, and remove the USB installer. Boot from USB again and
reapply:

```bash
just talos get-disks {node}
just talos apply-node {node}
```

### Wrong disk selected

Boot from USB installer, correct `disk_model` in `talos/nodes.yaml`, and reapply:

```bash
just talos apply-node {node}
```

### Installation hangs

Wait 10 minutes. If still hung, power cycle the node, boot from USB, and retry.

### etcd won't rejoin after control plane swap

If the node comes back but etcd membership stays at 2, check that the old member was properly
removed:

```bash
just talos etcd-status
```

If a stale member entry exists, remove it manually:

```bash
talosctl etcd forfeit-leadership -n {stale-member-ip}
talosctl etcd remove-member -n {other-cp-ip} {stale-member-id}
```

Then reset and reinstall the problem node from scratch.

## References

- [Talos machine configuration][talos-machine-config]
- [Talos scaling down (etcd member removal)][talos-scaling-down]
- [Talos etcd maintenance][talos-etcd-maintenance]

[talos-machine-config]:
    https://www.talos.dev/v1.12/talos-guides/configuration/editing-machine-configuration/
[talos-scaling-down]: https://www.talos.dev/v1.12/talos-guides/howto/scaling-down/
[talos-etcd-maintenance]: https://www.talos.dev/v1.12/advanced/etcd-maintenance/
