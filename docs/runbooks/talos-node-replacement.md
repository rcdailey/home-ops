# Talos Node Replacement

Replace Talos system disks while preserving node identity. Requires talhelper, Talos USB installer,
and kubectl access.

## Table of Contents

- [System Disk Replacement](#system-disk-replacement)
- [Moving to Different Disk](#moving-to-different-disk)
- [Additional Verification](#additional-verification)
- [Troubleshooting](#troubleshooting)
- [References](#references)

## System Disk Replacement

For control plane nodes, ensure cluster has quorum without this node before starting.

1. Check current disk. Note the MODEL field.

   ```bash
   talosctl -e {node-ip} -n {node-ip} get disks
   ```

2. Shutdown node and boot USB installer.

   ```bash
   talosctl -n {node-ip} shutdown
   ```

   Insert Talos USB installer, power on node, boot from USB.

3. Identify new disk. Record the exact MODEL string.

   ```bash
   talosctl disks --insecure --nodes {node-ip}
   ```

4. Update configuration. Edit `talos/talconfig.yaml`:

   ```yaml
   nodes:
   - hostname: "{node-hostname}"
     ipAddress: "{node-ip}"
     installDiskSelector:
       model: "{NEW_DISK_MODEL}"
   ```

   Regenerate configs:

   ```bash
   task talos:generate-config
   ```

5. Install Talos. Node will reboot automatically. Wait 5-8 minutes for installation and rejoin.

   ```bash
   talosctl apply-config --insecure \
     --nodes {node-ip} \
     --file talos/clusterconfig/home-ops-{node-hostname}.yaml
   ```

6. Verify installation.

   ```bash
   kubectl get node {node-hostname}
   talosctl -n {node-ip} version
   talosctl -e {node-ip} -n {node-ip} get disks
   ```

## Moving to Different Disk

Moving OS from one disk to another (e.g., SATA to NVMe). New disk must be physically installed
before starting.

Follow [System Disk Replacement](#system-disk-replacement) procedure. Both disks will be visible
during disk identification. Ensure `installDiskSelector` targets the NEW disk model. Old disk
remains untouched after installation.

## Additional Verification

```bash
# View system disk
talosctl -e {node-ip} -n {node-ip} get systemdisk

# Check mounts
talosctl -n {node-ip} get mounts

# View services
talosctl -n {node-ip} services

# Check logs
talosctl -n {node-ip} dmesg
```

## Troubleshooting

### Node Won't Boot

Check physical connections, BIOS boot order, remove USB installer. Boot from USB again and reapply:

```bash
talosctl disks --insecure --nodes {node-ip}
talosctl apply-config --insecure \
  --nodes {node-ip} \
  --file talos/clusterconfig/home-ops-{node-hostname}.yaml
```

### Wrong Disk Selected

Boot from USB installer, correct `talconfig.yaml` disk model, regenerate and reapply:

```bash
task talos:generate-config
talosctl apply-config --insecure --nodes {node-ip} --file talos/clusterconfig/home-ops-{node-hostname}.yaml
```

### Installation Hangs

Wait 10 minutes. If still hung, power cycle node, boot from USB, retry configuration application.

## References

- [Talos Machine Configuration][talos-machine-config]
- [talosctl apply-config Documentation][talos-apply-config]
- [talhelper Documentation][talhelper-docs]

[talos-machine-config]:
    https://github.com/siderolabs/talos/blob/main/website/content/v1.11/talos-guides/configuration/editing-machine-configuration.md
[talos-apply-config]:
    https://github.com/siderolabs/talos/blob/main/website/content/v1.11/talos-guides/configuration/editing-machine-configuration.md
[talhelper-docs]: https://github.com/budimanjojo/talhelper
