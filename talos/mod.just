set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

talos_dir := source_directory()
root_dir := parent_directory(talos_dir)
topf_file := talos_dir / "topf.yaml"

[private]
default:
    @just --list talos

# Raw topf access with Infisical secrets, for targeting and debugging beyond the recipes below.
[private]
[positional-arguments]
topf *args:
    #!/usr/bin/env bash
    set -euo pipefail
    just ensure-login
    cd "{{talos_dir}}"
    infisical run --silent --env=prod --path=/bootstrap -- topf "$@"

[doc('Summarize changes on all nodes, confirm once, then apply one node at a time')]
apply:
    #!/usr/bin/env bash
    set -euo pipefail
    just ensure-login
    cd "{{talos_dir}}"
    infisical run --silent --env=prod --path=/bootstrap -- ./apply.sh

[doc('Apply config to one node')]
apply-node node:
    @just talos topf apply --nodes-filter '^{{node}}$'

[doc('Preview config changes on all nodes (exits non-zero when changes exist)')]
diff:
    @just talos topf apply --dry-run

[doc('Show stage, readiness, and Talos version of every node')]
nodes:
    @just talos topf nodes

[confirm("Drain the node, remove it from etcd, wipe its system disk, and shut it down?")]
[doc('Reset a node: drain, leave etcd, wipe the system disk, shut down')]
reset-node node:
    @just talos topf reset --shutdown --confirm=false --nodes-filter '^{{node}}$'

[doc('Show disks on a node, including one booted from the installer (maintenance mode)')]
get-disks node:
    #!/usr/bin/env bash
    set -euo pipefail
    ip=$(NODE="{{node}}" yq '.nodes[] | select(.host == strenv(NODE)) | .ip' "{{topf_file}}")
    [[ -n "$ip" ]] || { echo "[error] Unknown node: {{node}}" >&2; exit 1; }
    # The maintenance service has no client certs yet, so it only answers --insecure requests.
    insecure=$(timeout 3 talosctl get machinestatus --insecure -n "$ip" &>/dev/null &&
        echo --insecure || true)
    talosctl get disks -n "$ip" $insecure

[doc('Generate talosconfig from the cluster secrets bundle')]
init-config:
    @just talos topf talosconfig > "{{talos_dir}}/talosconfig"

[doc('Download the installer ISO for the Talos version and schematic in topf.yaml')]
download-image:
    #!/usr/bin/env bash
    set -euo pipefail
    version=$(yq '.talosVersion' "{{topf_file}}")
    schematic=$(just talos topf schematic-ids)
    output="{{talos_dir}}/talos-${version}-${schematic:0:8}.iso"
    just log info "Downloading Talos $version..." schematic="$schematic"
    curl -sfL --retry 5 --retry-delay 5 --retry-all-errors -o "$output" \
        "https://factory.talos.dev/image/$schematic/$version/metal-amd64.iso"
    just log info "Downloaded" path="$output"

[doc('Show etcd status from every control-plane node; fails if one does not respond')]
etcd-status:
    #!/usr/bin/env bash
    set -euo pipefail
    nodes=$(yq '[.nodes[] | select(.role == "control-plane") | .ip] | join(",")' "{{topf_file}}")
    talosctl etcd status -n "$nodes"

[doc('Take an etcd snapshot once every control-plane etcd member responds')]
etcd-snapshot:
    #!/usr/bin/env bash
    set -euo pipefail
    just talos etcd-status
    cp_ip=$(yq '[.nodes[] | select(.role == "control-plane")][0].ip' "{{topf_file}}")
    timestamp=$(date +%Y%m%d-%H%M%S)
    output="{{root_dir}}/etcd-backup-${timestamp}.snapshot"
    checksum="${output}.sha256"
    just log info "Taking etcd snapshot..."
    talosctl etcd snapshot -n "$cp_ip" "$output"
    chmod 600 "$output"
    sha256sum "$output" > "$checksum"
    chmod 600 "$checksum"
    sha256sum --check "$checksum"
    just log info "Snapshot and checksum saved" snapshot="$output" checksum="$checksum"
