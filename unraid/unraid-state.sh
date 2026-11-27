#!/usr/bin/env bash
# Writes Unraid array, disk, parity check, and mover state for the node_exporter textfile collector.
# Reads only the state files emhttp maintains, so it never wakes a spun-down disk.
# /boot/config/go starts it at boot. Install: docs/runbooks/unraid-telemetry.md.
set -uo pipefail

readonly emhttp=/var/local/emhttp
readonly out_dir=/var/local/node-exporter/textfile
readonly interval=15

array_metrics() {
  awk -F'"' '
    /^mdState=/ { started = ($2 == "STARTED") }
    /^mdResync=/ { resync = $2 + 0 }
    /^mdResyncPos=/ { position = $2 + 0 }
    /^mdResyncSize=/ { size = $2 + 0 }
    /^shareMoverActive=/ { mover = ($2 == "yes") }
    END {
      print "# HELP unraid_array_started Whether the array is started."
      print "# TYPE unraid_array_started gauge"
      printf "unraid_array_started %d\n", started
      print "# HELP unraid_parity_check_progress_ratio Parity check or rebuild progress; 0 when idle."
      print "# TYPE unraid_parity_check_progress_ratio gauge"
      printf "unraid_parity_check_progress_ratio %.6f\n", (resync > 0 && size > 0) ? position / size : 0
      print "# HELP unraid_mover_running Whether the mover is moving files."
      print "# TYPE unraid_mover_running gauge"
      printf "unraid_mover_running %d\n", mover
    }' "$emhttp/var.ini"
}

disk_metrics() {
  awk -F'"' '
    /^\[/ { disk = $2; order[++count] = disk; next }
    /^type=/ { type[disk] = $2 }
    /^status=/ { status[disk] = $2 }
    /^spundown=/ { spun_down[disk] = $2 }
    /^temp=/ { temp[disk] = $2 }
    END {
      print "# HELP unraid_disk_spun_down Whether the disk is spun down."
      print "# TYPE unraid_disk_spun_down gauge"
      print "# HELP unraid_disk_temperature_celsius Disk temperature from emhttp; absent when unknown."
      print "# TYPE unraid_disk_temperature_celsius gauge"
      for (i = 1; i <= count; i++) {
        disk = order[i]
        if (type[disk] == "Flash" || status[disk] ~ /^DISK_NP/) continue
        labels = sprintf("{disk=\"%s\",type=\"%s\"}", disk, type[disk])
        printf "unraid_disk_spun_down%s %d\n", labels, spun_down[disk]
        if (temp[disk] ~ /^[0-9]+$/) printf "unraid_disk_temperature_celsius%s %d\n", labels, temp[disk]
      }
    }' "$emhttp/disks.ini"
}

write_metrics() {
  [[ -r $emhttp/var.ini && -r $emhttp/disks.ini ]] || return 1
  array_metrics && disk_metrics || return 1
  echo "# HELP unraid_state_last_update_timestamp_seconds When this state was last written."
  echo "# TYPE unraid_state_last_update_timestamp_seconds gauge"
  echo "unraid_state_last_update_timestamp_seconds $(date +%s)"
}

mkdir -p "$out_dir"
while true; do
  # node_exporter reads only *.prom files, so it never sees a partly written state file.
  if write_metrics >"$out_dir/unraid.prom.tmp"; then
    mv -f "$out_dir/unraid.prom.tmp" "$out_dir/unraid.prom"
  fi
  sleep "$interval"
done
