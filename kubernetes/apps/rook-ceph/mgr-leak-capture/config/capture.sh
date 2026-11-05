#!/usr/bin/env bash
# Temporary memory capture for https://tracker.ceph.com/issues/82544. Samples the local ceph-mgr
# every minute and runs one daily clone measurement:
#   MODE=manual: one manual clone of SOURCE_SUBVOLUME at TRIGGER_AT (UTC)
#   MODE=csi: from TRIGGER_AT, wait for the ceph-csi clone, then run one manual clone
# Each clone gets smaps, perf dump and RSS just before and 2 minutes after it finishes.
set -uo pipefail

OUT=/data
CAPTURES=$OUT/captures
mkdir -p "$CAPTURES"

export CEPH_CONF=/tmp/ceph.conf
keyring=/tmp/keyring
printf '[%s]\nkey = %s\n' "$CEPH_USERNAME" "$(cat /etc/rook-secret/ceph-secret)" >"$keyring"
mon_host=$(sed -E 's/[a-z0-9_-]+=//g' /etc/rook-mon/data)
printf '[global]\nmon_host = %s\n\n[%s]\nkeyring = %s\n' \
  "$mon_host" "$CEPH_USERNAME" "$keyring" >"$CEPH_CONF"

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$OUT/events.log"; }
ceph() { command ceph "$@" 2>>"$OUT/ceph-stderr.log"; }

mgr_pid() {
  local p
  for p in /proc/[0-9]*; do
    [[ $(cat "$p/comm" 2>/dev/null) == ceph-mgr ]] || continue
    tr '\0' ' ' <"$p/cmdline" | grep -Eq -- "--id[= ]$MGR_ID( |$)" && { basename "$p"; return; }
  done
}

status_kb() { awk -v k="$2:" '$1 == k {print $2}' "/proc/$1/status"; }

sampler() {
  [[ -f $OUT/rss.csv ]] || echo "time,pid,vmrss_kb,rssanon_kb" >"$OUT/rss.csv"
  while true; do
    local pid
    pid=$(mgr_pid)
    if [[ -n $pid ]]; then
      echo "$(date -u +%FT%TZ),$pid,$(status_kb "$pid" VmRSS),$(status_kb "$pid" RssAnon)" \
        >>"$OUT/rss.csv"
    fi
    sleep 60
  done
}

capture() {
  local dir pid
  dir=$CAPTURES/$(date -u +%Y%m%dT%H%M%SZ)-$1
  mkdir -p "$dir"
  pid=$(mgr_pid)
  grep -E '^(VmRSS|RssAnon|RssFile|Threads):' "/proc/$pid/status" >"$dir/status.txt"
  gzip -c "/proc/$pid/smaps" >"$dir/smaps.gz"
  ceph tell "mgr.$MGR_ID" perf dump >"$dir/perf-dump.json"
  log "captured $1 in $dir ($(tr '\n' ' ' <"$dir/status.txt"))"
}

# rbytes and rentries of a subvolume snapshot, read through libcephfs.
snapshot_stats() {
  local group=$1 subvol=$2 snap=$3 path
  path=$(ceph fs subvolume info "$FS" "$subvol" --group_name "$group" -f json | jq -r .path)
  python3 - "$FS" "$(dirname "$path")/.snap/$snap/$(basename "$path")" <<'EOF'
import sys
import cephfs

fs = cephfs.LibCephFS(conffile="/tmp/ceph.conf")
fs.mount(filesystem_name=sys.argv[1].encode())
values = [fs.getxattr(sys.argv[2].encode(), a).decode()
          for a in ("ceph.dir.rbytes", "ceph.dir.rentries")]
print("rbytes=%s rentries=%s" % tuple(values))
fs.shutdown()
EOF
}

# Waits for a clone to finish; prints its final state.
wait_clone() {
  local state
  for _ in $(seq 1 720); do
    state=$(ceph fs clone status "$FS" "$@" -f json | jq -r .status.state)
    [[ $state == complete || $state == failed ]] && break
    sleep 10
  done
  echo "$state"
}

manual_clone() {
  local snap clone start state
  snap=mgrleak-$(date -u +%Y%m%d%H%M)
  clone=$snap-clone
  ceph fs subvolume snapshot create "$FS" "$SOURCE_SUBVOLUME" "$snap" --group_name "$SOURCE_GROUP"
  log "manual snapshot $snap $(snapshot_stats "$SOURCE_GROUP" "$SOURCE_SUBVOLUME" "$snap")"
  capture manual-before
  start=$(date -u +%FT%TZ)
  ceph fs subvolume snapshot clone "$FS" "$SOURCE_SUBVOLUME" "$snap" "$clone" \
    --group_name "$SOURCE_GROUP"
  state=$(wait_clone "$clone")
  log "manual clone $clone state=$state start=$start finish=$(date -u +%FT%TZ)"
  ceph fs subvolume rm "$FS" "$clone"
  ceph fs subvolume snapshot rm "$FS" "$SOURCE_SUBVOLUME" "$snap" --group_name "$SOURCE_GROUP"
  sleep 120
  capture manual-after
}

csi_names() { ceph fs subvolume ls "$FS" --group_name csi -f json | jq -r '.[].name' | sort; }

csi_clone() {
  local baseline new start state source
  capture csi-before
  baseline=$(csi_names)
  for _ in $(seq 1 720); do
    new=$(comm -13 <(echo "$baseline") <(csi_names) | head -1)
    [[ -n $new ]] && break
    sleep 15
  done
  if [[ -z $new ]]; then
    log "no ceph-csi clone appeared within 3h"
    return
  fi
  start=$(date -u +%FT%TZ)
  state=$(wait_clone "$new" --group_name csi)
  source=$(ceph fs clone status "$FS" "$new" --group_name csi -f json | jq -c .status.source)
  log "csi clone $new state=$state first_seen=$start finish=$(date -u +%FT%TZ) source=$source"
  if [[ $source != null ]]; then
    log "csi snapshot $(snapshot_stats "$(jq -r .group <<<"$source")" \
      "$(jq -r .subvolume <<<"$source")" "$(jq -r .snapshot <<<"$source")")"
  fi
  sleep 120
  capture csi-after
  manual_clone
}

log "start mode=$MODE trigger=$TRIGGER_AT mgr=$MGR_ID pid=$(mgr_pid)"
sampler &
last_run=""
while true; do
  today=$(date -u +%F)
  if [[ $(date -u +%H:%M) == "$TRIGGER_AT" && $today != "$last_run" ]]; then
    last_run=$today
    log "daily run, active mgr=$(ceph mgr stat -f json | jq -r .active_name)"
    if [[ $MODE == csi ]]; then csi_clone; else manual_clone; fi
  fi
  sleep 20
done
