# Unraid NFS drain

Before nezuko (Unraid) stops its array, it asks the cluster to scale every NFS-dependent app to zero
and waits 90 seconds so the pods stop while NFS is still up. Without the drain, the cluster notices
only after NFS is gone, and pods hang in Terminating on dead NFS mounts.

Nezuko's metrics and logs are covered in [Unraid telemetry][telemetry].

## How it works

1. A planned reboot or shutdown runs `/boot/config/stop` before Unraid starts its 90 second array
   stop timer. A manual "Stop array" runs the emhttp `stopping` event hook. Both run
   [`unraid/nfs-drain.sh`][script], and Unraid waits for it to finish.
2. The script pushes `nfs_drain_requested 1` every 10 seconds to VictoriaMetrics through the
   internal gateway. Only `192.168.1.58` may write, and only to `/api/v1/import/prometheus`.
3. prometheus-adapter reports the `probe_success` external metric as 0 while a sample from the last
   2 minutes exists, so the `nfs-scaler` HPAs scale their apps to zero.
4. The signal expires 2 minutes after the last push. By then the NFS probe reports NFS down, so the
   apps stay at zero until NFS returns. Nothing needs to be cleared after Unraid comes back.

If the first three pushes fail, the script stops waiting and Unraid continues to stop. A pod that
needs more than 90 seconds to stop still loses NFS.

The User Scripts plugin's "At Stopping of Array" schedule cannot run the drain: it starts scripts in
the background after Docker has stopped, so Unraid does not wait for them.

## Files on nezuko

| Path                                                | Survives reboot | Purpose                                               |
| --------------------------------------------------- | --------------- | ----------------------------------------------------- |
| `/boot/config/home-ops/nfs-drain`                   | yes (flash)     | Drain script, copy of [`unraid/nfs-drain.sh`][script] |
| `/boot/config/home-ops/nfs-drain.env`               | yes (flash)     | `VM_HOST`; not in Git                                 |
| `/boot/config/home-ops/README`                      | yes (flash)     | Points back to this runbook                           |
| `/boot/config/home-ops/go.bak`                      | yes (flash)     | `go` file before the hook block was added             |
| `/boot/config/stop`                                 | yes (flash)     | Runs the drain on reboot or shutdown                  |
| `/boot/config/go`                                   | yes (flash)     | Hook block at the end installs the event hook at boot |
| `/usr/local/emhttp/plugins/home-ops/event/stopping` | no (RAM)        | Event hook for manual "Stop array"                    |
| `/var/run/nfs-drain.done`                           | no (RAM)        | Marker that skips the second drain during a reboot    |

The drain logs to the Unraid syslog with the tag `nfs-drain`. Nothing appears in the User Scripts
plugin or elsewhere in the web UI.

## Install

Run from a workstation in the repository root. `SECRET_DOMAIN` must be set.

1. Copy the script and the stop file to the flash drive.

   ```bash
   ssh nezuko 'mkdir -p /boot/config/home-ops'
   scp unraid/nfs-drain.sh nezuko:/boot/config/home-ops/nfs-drain
   scp unraid/README.md nezuko:/boot/config/home-ops/README
   scp unraid/stop.sh nezuko:/boot/config/stop
   ```

2. Write the VictoriaMetrics hostname. Unraid cannot resolve internal names, so the script connects
   to the gateway IP and uses this name for TLS.

   ```bash
   ssh nezuko "echo VM_HOST=victoria-metrics.${SECRET_DOMAIN} > /boot/config/home-ops/nfs-drain.env"
   ```

3. Append the hook installer to `/boot/config/go`, then run it once so the hook exists without a
   reboot. `/usr/local/emhttp` is rebuilt in RAM on every boot.

   ```bash
   ssh nezuko 'cat >> /boot/config/go' <<'EOF'

   # NFS drain hook for the home-ops cluster (docs/runbooks/unraid-nfs-drain.md)
   mkdir -p /usr/local/emhttp/plugins/home-ops/event
   install -m 755 /boot/config/home-ops/nfs-drain /usr/local/emhttp/plugins/home-ops/event/stopping
   EOF
   ssh nezuko 'mkdir -p /usr/local/emhttp/plugins/home-ops/event &&
     install -m 755 /boot/config/home-ops/nfs-drain /usr/local/emhttp/plugins/home-ops/event/stopping'
   ```

After a script change, repeat the copy in step 1 and the `install` command in step 3.

## Test

1. Run a drain without stopping anything. NFS apps scale to zero about 35 seconds after the script
   starts and return about 2.5 minutes after it ends.

   ```bash
   ssh nezuko 'bash /boot/config/home-ops/nfs-drain test'
   kubectl get hpa -A -w
   ```

2. Read the result in the Unraid syslog.

   ```bash
   ssh nezuko 'grep nfs-drain /var/log/syslog'
   ```

3. Confirm that writes from other LAN hosts are refused (403).

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' --data-binary 'x 1' \
     "https://victoria-metrics.${SECRET_DOMAIN}/api/v1/import/prometheus"
   ```

## Remove

```bash
ssh nezuko 'rm -rf /boot/config/home-ops /boot/config/stop /usr/local/emhttp/plugins/home-ops'
```

Then delete the hook block from `/boot/config/go`.

[script]: ../../unraid/nfs-drain.sh
[telemetry]: ./unraid-telemetry.md
