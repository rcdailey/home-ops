# Talos node replacement

Replace Talos system disks while preserving node identity. Requires a Talos USB installer and
kubectl access.

## Table of contents

- [Node reference](#node-reference)
- [Control plane disk replacement](#control-plane-disk-replacement)
- [Worker disk replacement](#worker-disk-replacement)
- [Moving to a different disk](#moving-to-a-different-disk)
- [Additional verification](#additional-verification)
- [Troubleshooting](#troubleshooting)
- [References](#references)

## Node reference

| Node     | Role          | IP           | Current disk (sda)     |
| -------- | ------------- | ------------ | ---------------------- |
| hanekawa | control plane | 192.168.1.63 | INTEL SSDSC2BA40 400GB |
| marin    | control plane | 192.168.1.59 | INTEL SSDSC2BA40 400GB |
| sakura   | control plane | 192.168.1.62 | Samsung 870 EVO 250GB  |
| lucy     | worker        | 192.168.1.54 | SanDisk SDSSDH32 2TB   |
| nami     | worker        | 192.168.1.50 | Crucial BX500 2TB      |

## Control plane disk replacement

Control plane nodes run etcd, which needs a 2-of-3 majority to function. Do one node at a time and
verify full rejoin before touching the next.

1. Take an etcd snapshot from one of the other control plane nodes. This is your safety net if
   something goes wrong during the swap.

   ```bash
   talosctl etcd snapshot -n {other-cp-ip} /tmp/etcd-backup.snapshot
   ```

2. Confirm etcd is healthy and all three members are present.

   ```bash
   talosctl etcd members -n {other-cp-ip}
   ```

3. Reset the node. This cordons, drains, leaves the etcd cluster, wipes the Talos system disk (sda),
   and shuts down the machine. The Ceph OSD (nvme0n1) is not touched.

   ```bash
   talosctl reset -n {node-ip}
   ```

   Wait for the node to fully shut down before continuing.

4. Remove the stale Kubernetes node object.

   ```bash
   kubectl delete node {node-hostname}
   ```

5. Physically swap the drive. Insert the Talos USB installer and power on the node, booting from
   USB.

6. Identify the new disk. Record the exact MODEL string.

   ```bash
   talosctl get disks --insecure -n {node-ip}
   ```

7. Update `talos/nodes.yaml` with the new disk model:

   ```yaml
   nodes:
     {node-hostname}:
       disk_model: "{NEW_DISK_MODEL}"
   ```

   Remove the `disk_size` field if present (only needed when two disks share the same model prefix).

8. Apply the config. The node installs to the new disk and reboots automatically. Wait 5-8 minutes
   for it to rejoin the cluster and re-enter etcd membership.

   ```bash
   just talos apply-node {node-hostname} --insecure
   ```

9. Verify the node is back and etcd has three healthy members again. Don't move on to the next node
   until this looks right.

   ```bash
   kubectl get node {node-hostname}
   talosctl version -n {node-ip}
   talosctl get disks -n {node-ip}
   talosctl etcd members -n {node-ip}
   talosctl etcd status -n {node-ip}
   ```

Repeat from step 1 for the next control plane node.

## Worker disk replacement

Workers don't run etcd, so the procedure is simpler. No snapshot or etcd verification needed.

1. Check the current disk. Note the MODEL field.

   ```bash
   talosctl get disks -n {node-ip}
   ```

2. Shut down the node.

   ```bash
   talosctl shutdown -n {node-ip}
   ```

   Insert the Talos USB installer, power on, and boot from USB.

3. Identify the new disk. Record the exact MODEL string.

   ```bash
   talosctl get disks --insecure -n {node-ip}
   ```

4. Update `talos/nodes.yaml` with the new disk model (see [step 7](#control-plane-disk-replacement)
   for format).

5. Apply the config. The node installs and reboots automatically. Wait 5-8 minutes for it to rejoin.

   ```bash
   just talos apply-node {node-hostname} --insecure
   ```

6. Verify installation.

   ```bash
   kubectl get node {node-hostname}
   talosctl version -n {node-ip}
   talosctl get disks -n {node-ip}
   ```

## Moving to a different disk

Moving the OS from one disk to another (e.g., SATA to NVMe) when the new disk is already physically
installed alongside the old one.

Follow the [control plane](#control-plane-disk-replacement) or [worker](#worker-disk-replacement)
procedure as appropriate. Both disks will be visible during disk identification. Make sure
`disk_model` in `talos/nodes.yaml` targets the new disk. The old disk remains untouched after
installation.

## Additional verification

These are useful if something feels off after a swap.

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

## Troubleshooting

### Node won't boot

Check physical connections, BIOS boot order, and remove the USB installer. Boot from USB again and
reapply:

```bash
talosctl get disks --insecure -n {node-ip}
just talos apply-node {node-hostname} --insecure
```

### Wrong disk selected

Boot from USB installer, correct `disk_model` in `talos/nodes.yaml`, and reapply:

```bash
just talos apply-node {node-hostname} --insecure
```

### Installation hangs

Wait 10 minutes. If still hung, power cycle the node, boot from USB, and retry.

### etcd won't rejoin after control plane swap

If the node comes back but etcd membership stays at 2, check that the old member was properly
removed:

```bash
talosctl etcd members -n {other-cp-ip}
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
