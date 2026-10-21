set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

# Module imports
mod bootstrap "bootstrap"
mod talos "talos"
# Single-file structure must be used when no other supporting files exist
mod infisical ".justfiles/infisical.just"
mod kubernetes ".justfiles/kubernetes.just"
mod secret ".justfiles/secret.just"

# Directory variables
root_dir := justfile_directory()
kubernetes_dir := root_dir / "kubernetes"

[private]
default:
    @just --list

[doc('Force Flux to pull changes from Git repository')]
reconcile:
    flux --namespace flux-system reconcile kustomization flux-system --with-source

[private]
log level msg *args:
    @echo "[{{level}}] {{msg}}" {{args}}

# Without a TTY, `infisical login` prints the browser URL instead of opening it and then blocks.
# Open the URL ourselves so non-interactive callers (agents, scripts) can wait for the user.
[private]
ensure-login:
    #!/usr/bin/env bash
    set -euo pipefail
    infisical login status &>/dev/null && exit 0
    log=$(mktemp)
    trap 'rm -f "$log"' EXIT
    infisical login --domain="https://app.infisical.com" </dev/null &>"$log" &
    pid=$!
    until url=$(rg -o -m1 --no-line-number 'https://\S+callback_port=\d+' "$log"); do
        if ! kill -0 "$pid" 2>/dev/null; then
            cat "$log" >&2
            exit 1
        fi
        sleep 0.2
    done
    echo "[info] Waiting for Infisical login in browser: $url" >&2
    xdg-open "$url" &>/dev/null || true
    wait "$pid"

[private]
template file *args:
    @just ensure-login
    infisical run --env=prod --path=/bootstrap -- minijinja-cli "{{ file }}" {{ args }}
