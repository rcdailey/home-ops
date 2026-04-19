#!/usr/bin/env bash
# Run a command on a UniFi device via SSH with a timeout.
#
# Usage: unifi-ssh.sh [options] <host> <command...>
#
# Options (applied on the REMOTE side via BusyBox):
#   -f PATTERN   filter output lines matching PATTERN (remote grep -E)
#   -F PATTERN   filter OUT lines matching PATTERN (remote grep -vE)
#   -i           case-insensitive filter (applies to -f/-F)
#   -n N         limit output to first N lines (remote head -n N)
#
# Filters exist because ripgrep is not available on UniFi devices; this wrapper
# lets the caller avoid typing 'grep' / 'head' in the local command string.
#
# Example:
#   unifi-ssh.sh 192.168.1.202 swctrl port show counters id 6
#   unifi-ssh.sh -f '^Port|Error|Discard' 192.168.1.202 swctrl port show counters id 6
#   unifi-ssh.sh -f switch -i 192.168.1.202 ps
set -euo pipefail

filter=""
filter_v=""
nocase=""
head_n=""

while getopts "f:F:in:" opt; do
  case "$opt" in
    f) filter="$OPTARG" ;;
    F) filter_v="$OPTARG" ;;
    i) nocase="i" ;;
    n) head_n="$OPTARG" ;;
    *) echo "unknown option" >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))

host="${1:?host required (ip or name)}"
shift

remote_cmd="$*"
if [[ -n "$filter" ]]; then
  remote_cmd+=" | grep -E${nocase} -- $(printf '%q' "$filter")"
fi
if [[ -n "$filter_v" ]]; then
  remote_cmd+=" | grep -vE${nocase} -- $(printf '%q' "$filter_v")"
fi
if [[ -n "$head_n" ]]; then
  remote_cmd+=" | head -n $head_n"
fi

ssh \
  -o StrictHostKeyChecking=no \
  -o BatchMode=yes \
  -o ConnectTimeout=5 \
  -o ServerAliveInterval=5 \
  -o ServerAliveCountMax=2 \
  -o LogLevel=ERROR \
  "admin@${host}" \
  "timeout -t 15 sh -c $(printf '%q' "$remote_cmd") 2>&1"
