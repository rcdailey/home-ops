#!/usr/bin/env bash
# Write the age identity stored in a Bitwarden secure note to a gitignored file.
#
# Usage: age-key.sh [note-name]
#
# The note body must be the output of `age-keygen`. The default note name is "home-ops age key".
# The file is written to <repo>/age.txt, owned by the current user with mode 0600. When the file
# already exists, only its ownership and mode are corrected; delete it first to fetch the key again.
set -euo pipefail

note="${1:-home-ops age key}"
repo_root="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
target="$repo_root/age.txt"

if [[ -e $target ]]; then
  chown "$(id -u):$(id -g)" "$target"
  chmod 600 "$target"
  echo "secured existing $target"
  exit 0
fi

if ! rbw unlocked 2>/dev/null; then
  rbw unlock
fi

key="$(rbw get --raw "$note" | jq -r '.notes // empty')"
if [[ $key != *AGE-SECRET-KEY-* ]]; then
  echo "error: note '$note' does not contain an AGE-SECRET-KEY line" >&2
  exit 1
fi

umask 077
tmp="$(mktemp "$target.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
printf '%s\n' "$key" >"$tmp"
mv "$tmp" "$target"
echo "wrote $target"
