# Unraid telemetry

Nezuko (Unraid) sends host metrics, Unraid state, and its system log to the cluster. The cluster
scrapes metrics from node_exporter on Nezuko, and Unraid's remote syslog sends each log line to the
OpenTelemetry gateway through the internal gateway.

## How it works

- node_exporter runs as the `node-exporter` Docker container on the host network, port 9100. The
  `nezuko` scrape job in `kubernetes/apps/observability/opentelemetry-scrape/collector.yaml` reads
  it every 20 seconds.
- [`unraid/unraid-state.sh`][state] writes `unraid_*` metrics every 15 seconds to
  `/var/local/node-exporter/textfile/unraid.prom`, which node_exporter's textfile collector serves.
  It reads only the state files emhttp maintains, so it never wakes a spun-down disk.
- Unraid's rsyslog forwards every line over UDP to `192.168.50.72:514`. The internal gateway passes
  it to the gateway Collector's syslog receiver, which queues it on disk until VictoriaLogs accepts
  it. Lines sent while no gateway Collector is reachable are lost.

The `ScrapeTargetDown` alert covers node_exporter, and `UnraidStateStale` covers the state script.

| Metric                                       | Meaning                                    |
| -------------------------------------------- | ------------------------------------------ |
| `unraid_array_started`                       | 1 while the array is started               |
| `unraid_disk_spun_down{disk,type}`           | 1 while the disk is spun down              |
| `unraid_disk_temperature_celsius{disk,type}` | Absent while the disk is spun down         |
| `unraid_parity_check_progress_ratio`         | Parity check or rebuild progress, 0 idle   |
| `unraid_mover_running`                       | 1 while the mover is moving files          |
| `unraid_state_last_update_timestamp_seconds` | Last write by the state script             |

## Files on nezuko

The container template is `my-node-exporter.xml` in `/boot/config/plugins/dockerMan/templates-user`
on the flash drive.

| Path                                            | Survives reboot  | Purpose                  |
| ----------------------------------------------- | ---------------- | ------------------------ |
| `/boot/config/home-ops/unraid-state`            | yes (flash)      | Copy of the state script |
| `/boot/config/go`                               | yes (flash)      | Starts the state script  |
| `/var/lib/docker/unraid-autostart`              | yes (docker.img) | Starts node_exporter     |
| `/var/local/node-exporter/textfile/unraid.prom` | no (RAM)         | State script output      |

## Install

Run from a workstation in the repository root.

1. Copy the state script and the container template.

   ```bash
   ssh nezuko 'mkdir -p /boot/config/home-ops'
   scp unraid/unraid-state.sh nezuko:/boot/config/home-ops/unraid-state
   scp unraid/my-node-exporter.xml \
     nezuko:/boot/config/plugins/dockerMan/templates-user/my-node-exporter.xml
   ```

2. Append the state script starter to `/boot/config/go`, then start it once.

   ```bash
   ssh nezuko 'cat >> /boot/config/go' <<'EOF'

   # Unraid state for node_exporter (docs/runbooks/unraid-telemetry.md)
   install -m 755 /boot/config/home-ops/unraid-state /usr/local/sbin/unraid-state
   setsid /usr/local/sbin/unraid-state >/dev/null 2>&1 </dev/null &
   EOF
   ssh nezuko 'install -m 755 /boot/config/home-ops/unraid-state /usr/local/sbin/unraid-state &&
     (setsid /usr/local/sbin/unraid-state >/dev/null 2>&1 </dev/null &)'
   ```

3. Create the container with the template's settings and add it to Docker autostart. Unraid's root
   mount is private, so the host root is mounted without `rslave`.

   ```bash
   ssh nezuko 'docker run -d --name node-exporter --net=host --pid=host \
     --restart=unless-stopped -l net.unraid.docker.managed=dockerman -v /:/host:ro \
     quay.io/prometheus/node-exporter:v1.13.1 --path.rootfs=/host \
     --collector.textfile.directory=/host/var/local/node-exporter/textfile &&
     echo node-exporter >> /var/lib/docker/unraid-autostart'
   ```

4. In the Unraid web UI, open Settings, Syslog Server. Set Remote syslog server to `192.168.50.72`,
   port `514`, protocol UDP, and apply. Confirm the forward line in the generated config:

   ```bash
   ssh nezuko 'grep -n 192.168.50.72 /etc/rsyslog.conf'
   ```

To update node_exporter, change the image tag in the template, copy it again, and edit the container
in the Docker tab so Unraid recreates it. After a state script change, repeat the copy in step 1,
stop the old process with `pkill -f /usr/local/sbin/unraid-state`, and repeat the second command in
step 2.

## Test

1. Confirm the exporter and the state metrics.

   ```bash
   ssh nezuko 'curl -s localhost:9100/metrics | grep -c "^unraid_"'
   ./scripts/hops.sh query query 'up{service_name="nezuko"}'
   ```

2. Send a test log line and find it in VictoriaLogs.

   ```bash
   ssh nezuko 'logger -t telemetry-test "syslog path check"'
   ./scripts/hops.sh query logs query 'service.name:unraid-syslog telemetry-test' --from 10m
   ```

## Remove

```bash
ssh nezuko 'docker rm -f node-exporter; pkill -f /usr/local/sbin/unraid-state;
  sed -i "/^node-exporter$/d" /var/lib/docker/unraid-autostart;
  rm -f /boot/config/home-ops/unraid-state /usr/local/sbin/unraid-state \
    /boot/config/plugins/dockerMan/templates-user/my-node-exporter.xml'
```

Then delete the state script block from `/boot/config/go` and clear Remote syslog server in the
Unraid web UI.

[state]: ../../unraid/unraid-state.sh
