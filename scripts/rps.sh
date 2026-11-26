#!/usr/bin/env bash
# Run PowerShell on a Windows host over SSH, using a key and address stored in Bitwarden.
#
# Usage:
#   rps.sh list                          list host aliases
#   rps.sh <alias> run '<command>'       run one PowerShell command
#   rps.sh <alias> script <file|->       run a local .ps1 file (or stdin)
#   rps.sh <alias> pull <remote> <local> copy a file or glob from the host
#   rps.sh <alias> shell                 open an interactive session
#
# Each alias is an rbw entry in the "rps" folder: the username is the remote admin account, the
# URI is ssh://<host>, and the note holds the OpenSSH private key. Nothing that identifies a host
# lives in this script. The key is written to a private temporary file for the duration of one
# call and removed on exit. Commands are sent base64-encoded (-EncodedCommand), so quoting and
# multi-line scripts survive the SSH hop; progress output is suppressed to keep stdout clean.
set -euo pipefail

folder="rps"

usage() {
  sed -n '2,10s/^# \{0,1\}//p' "$0" >&2
  exit 2
}

[[ $# -ge 1 ]] || usage

if ! rbw unlocked 2>/dev/null; then
  rbw unlock
fi

if [[ $1 == list ]]; then
  rbw list --fields name,folder | awk -F'\t' -v f="$folder" '$2 == f { print $1 }'
  exit 0
fi

[[ $# -ge 2 ]] || usage
alias_name="$1" action="$2"
shift 2

entry="$(rbw get --raw --folder "$folder" "$alias_name")"
user="$(jq -r '.data.username // empty' <<<"$entry")"
host="$(jq -r '.data.uris[0].uri // empty | sub("^ssh://"; "")' <<<"$entry")"
if [[ -z $user || -z $host ]]; then
  echo "error: rbw entry '$folder/$alias_name' needs a username and an ssh:// URI" >&2
  exit 1
fi

umask 077
key="$(mktemp "${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/rps.XXXXXX")"
trap 'rm -f "$key"' EXIT
jq -r '.notes // empty' <<<"$entry" >"$key"
if ! grep -q 'BEGIN OPENSSH PRIVATE KEY' "$key"; then
  echo "error: rbw entry '$folder/$alias_name' note does not hold an OpenSSH private key" >&2
  exit 1
fi

# The destination is the literal "rps"; HostName and User carry the real target.
ssh_opts=(-i "$key" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new
  -o ConnectTimeout=10 -o HostName="$host" -o User="$user")

# Encodes PowerShell source as UTF-16LE base64 for -EncodedCommand.
encode() {
  { printf '%s\n' "\$ProgressPreference = 'SilentlyContinue'"; cat; } |
    iconv -f UTF-8 -t UTF-16LE | base64 | tr -d '\n'
}

run_encoded() {
  ssh "${ssh_opts[@]}" -o BatchMode=yes rps \
    "powershell -NoProfile -NonInteractive -EncodedCommand $(encode)"
}

case "$action" in
  run)
    [[ $# -eq 1 ]] || usage
    printf '%s\n' "$1" | run_encoded
    ;;
  script)
    [[ $# -eq 1 ]] || usage
    if [[ $1 == - ]]; then run_encoded; else run_encoded <"$1"; fi
    ;;
  pull)
    [[ $# -eq 2 ]] || usage
    scp "${ssh_opts[@]}" -o BatchMode=yes -q "rps:$1" "$2"
    ;;
  shell)
    ssh "${ssh_opts[@]}" rps
    ;;
  *)
    usage
    ;;
esac
