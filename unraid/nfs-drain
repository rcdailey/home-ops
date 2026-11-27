#!/usr/bin/env bash
# Asks the cluster to scale NFS-dependent pods to zero, then waits so they stop before NFS does.
# Unraid runs it from /boot/config/stop on reboot or shutdown (argument "shutdown") and from the
# emhttp "stopping" array event (argument "stopping"). Install: docs/runbooks/unraid-nfs-drain.md.
set -uo pipefail

readonly config=/boot/config/home-ops/nfs-drain.env
readonly gateway_ip=192.168.50.72
readonly drain_seconds=90
readonly push_interval=10
readonly max_failed_pushes=3
# A reboot runs the stop file and then the stopping event; the marker makes the second run a no-op.
# /var/run is tmpfs, so the marker disappears with the reboot.
readonly marker=/var/run/nfs-drain.done

log() { logger -t nfs-drain "$*"; }

if [[ -e $marker ]]; then
  log "drain already done during this shutdown, skipping"
  exit 0
fi

if [[ ! -r $config ]]; then
  log "missing $config, not draining"
  exit 0
fi
# Provides VM_HOST, the VictoriaMetrics hostname on the internal gateway.
# shellcheck source=/dev/null
source "$config"

push_drain_request() {
  curl -fsS -m 5 --resolve "${VM_HOST}:443:${gateway_ip}" \
    --data-binary 'nfs_drain_requested 1' "https://${VM_HOST}/api/v1/import/prometheus"
}

log "requesting NFS drain, waiting ${drain_seconds}s"
pushed=0
failed=0
end=$((SECONDS + drain_seconds))
while ((SECONDS < end)); do
  if push_drain_request; then
    pushed=1
  else
    failed=$((failed + 1))
    log "drain request failed"
    if ((!pushed && failed >= max_failed_pushes)); then
      log "cluster unreachable, continuing without drain"
      exit 0
    fi
  fi
  sleep "$push_interval"
done

if [[ ${1:-} == shutdown ]]; then
  touch "$marker"
fi
log "drain wait finished"
