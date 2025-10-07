#!/usr/bin/env bash
# Generate Authelia-compatible argon2id password hash

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <password>"
  echo "Example: $0 'my-secure-password'"
  exit 1
fi

PASSWORD="$1"

# Generate argon2id hash with Authelia defaults
# -id: argon2id variant
# -t 3: 3 iterations
# -m 16: 65536 KiB memory (2^16)
# -p 4: 4 threads
# -l 32: 32 byte key length
# -e: encoded output format
echo -n "$PASSWORD" | argon2 "$(openssl rand -base64 16)" -id -t 3 -m 16 -p 4 -l 32 -e
