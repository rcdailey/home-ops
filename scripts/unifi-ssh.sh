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
# The UniFi OS console (the UNIFI_URL host) only accepts root; adopted devices use the
# controller's device SSH user (admin).
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

# Prints the IPv4 address of a name or literal, using the platform resolver (Linux or macOS).
resolve_ipv4() {
  if [[ "$1" =~ ^[0-9]+(\.[0-9]+){3}$ ]]; then
    echo "$1"
  elif command -v getent >/dev/null; then
    getent ahostsv4 "$1" | awk 'NR == 1 { print $1 }'
  else
    dscacheutil -q host -a name "$1" | awk '/^ip_address:/ { print $2; exit }'
  fi
}

console_host="${UNIFI_URL:?UNIFI_URL required}"
console_host="${console_host#*://}"
console_host="${console_host%%[:/]*}"
console_ip="$(resolve_ipv4 "$console_host" || true)"
host_ip="$(resolve_ipv4 "$host" || true)"
if [[ -z "$console_ip" || -z "$host_ip" ]]; then
  echo "cannot resolve ${host} or console ${console_host}" >&2
  exit 2
fi

ssh_user="admin"
if [[ "$host_ip" == "$console_ip" ]]; then
  ssh_user="root"
fi

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

quoted_remote_cmd="$(printf '%q' "$remote_cmd")"
legacy_timeout='timeout --help 2>&1 | grep -q -- "-t SECS"'
remote_timeout="timeout 15 sh -c $quoted_remote_cmd"
legacy_remote_timeout="timeout -t 15 sh -c $quoted_remote_cmd"
remote_exec="if $legacy_timeout; then $legacy_remote_timeout; else $remote_timeout; fi"

ssh \
  -o StrictHostKeyChecking=no \
  -o BatchMode=yes \
  -o ConnectTimeout=5 \
  -o ServerAliveInterval=5 \
  -o ServerAliveCountMax=2 \
  -o LogLevel=ERROR \
  "${ssh_user}@${host}" \
  "$remote_exec 2>&1"
