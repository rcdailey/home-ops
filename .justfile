set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

# Module imports
mod bootstrap "bootstrap"
mod talos "talos"
# Single-file structure must be used when no other supporting files exist
mod infisical ".justfiles/infisical.just"
mod kubernetes ".justfiles/kubernetes.just"

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

[private]
template file *args:
    infisical run --env=prod --path=/bootstrap -- minijinja-cli "{{ file }}" {{ args }}
