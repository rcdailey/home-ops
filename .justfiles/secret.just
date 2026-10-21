set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']
set positional-arguments := true

[private]
default:
    @just --list secret

[private]
validate key:
    [[ $1 =~ ^[A-Z_][A-Z0-9_]*$ ]] || { echo "[error] invalid env var name: $1" >&2; exit 1; }

[doc('Add or update an age-encrypted mise env secret; prompts, or reads the value from stdin')]
add key: (validate key)
    #!/usr/bin/env bash
    set -euo pipefail
    root=$(git rev-parse --show-toplevel)
    args=(--file "$root/.config/mise/conf.d/secrets.toml" --age-encrypt
        --age-key-file "$root/age.txt")
    if [[ -t 0 ]]; then
        mise set "${args[@]}" --prompt "$1"
    else
        mise set "${args[@]}" --stdin "$1"
    fi

[doc('Print the decrypted value of one mise env secret')]
get key: (validate key)
    mise env --json | jq -er --arg k "$1" '.[$k] // error("[error] \($k) is not set")'
