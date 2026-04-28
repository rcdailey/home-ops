set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

talos_dir := source_directory()
nodes_file := talos_dir / "nodes.yaml"
versions_file := talos_dir / "talenv.yaml"

[private]
default:
    @just --list talos

# Resolve node name (with fzf fallback), print "name ip is_controller"
[private]
resolve-node node prompt:
    #!/usr/bin/env bash
    set -euo pipefail
    node="{{node}}"
    if [ -z "$node" ]; then
        node=$(just talos select-node "{{prompt}}")
    fi
    ip=$(yq ".nodes.$node.ip" "{{nodes_file}}")
    if [ -z "$ip" ] || [ "$ip" = "null" ]; then
        echo "[error] Unknown node: $node" >&2
        exit 1
    fi
    controller=$(yq ".nodes.$node.controller" "{{nodes_file}}")
    echo "$node $ip $controller"

# Interactive node selection helper
[private]
select-node prompt="Select node":
    @yq '.nodes | keys | .[]' "{{nodes_file}}" | fzf --prompt="{{prompt}}: "

# Return first control plane node IP
[private]
cp-ip:
    @yq '.nodes | to_entries | map(select(.value.controller == true)) | .[0].value.ip' "{{nodes_file}}"

# Prints "--insecure" to stdout if node is in maintenance mode, warns on stderr.
# Uses "get machinestatus --insecure" as the probe because "version --insecure" is not
# implemented in the maintenance service. If the probe fails (node running normally,
# unreachable, or bad certs), outputs nothing and lets the actual command handle it.
[private]
detect-insecure node_ip:
    #!/usr/bin/env bash
    if timeout 3 talosctl get machinestatus --insecure -n "{{node_ip}}" &>/dev/null; then
        echo -e "\033[33m[warn] Node is in maintenance mode, using insecure connection\033[0m" >&2
        echo "--insecure"
    fi

# Fails if etcd cluster is not fully healthy (all CP members present and responding)
[private]
require-etcd-healthy:
    #!/usr/bin/env bash
    set -euo pipefail
    cp_ip=$(just talos cp-ip)
    expected=$(yq '[.nodes | to_entries[] | select(.value.controller == true)] | length' "{{nodes_file}}")
    output=$(talosctl etcd members -n "$cp_ip" 2>&1)
    actual=$(echo "$output" | tail -n +2 | grep -c '[^[:space:]]' || true)
    if [[ "$actual" -ne "$expected" ]]; then
        echo "$output" >&2
        just log error "etcd has $actual members (expected $expected)"
        exit 1
    fi
    if ! talosctl etcd status -n "$cp_ip" &>/dev/null; then
        just log error "etcd status check failed"
        exit 1
    fi

[doc('List available Talos nodes with IPs')]
list-nodes:
    #!/usr/bin/env bash
    set -euo pipefail
    for node in $(yq '.nodes | keys | .[]' "{{nodes_file}}"); do
        ip=$(yq ".nodes.$node.ip" "{{nodes_file}}")
        controller=$(yq ".nodes.$node.controller" "{{nodes_file}}")
        role=$([[ "$controller" == "true" ]] && echo "control-plane" || echo "worker")
        just log info "$node ($ip) [$role]"
    done

[doc('Show disks on a node (auto-detects maintenance mode)')]
get-disks node="":
    #!/usr/bin/env bash
    set -euo pipefail
    read -r node ip _ <<< "$(just talos resolve-node "{{node}}" "Select node")"
    flags=$(just talos detect-insecure "$ip")
    talosctl get disks -n "$ip" $flags

[doc('Initialize talosconfig from Infisical secrets')]
init-config:
    @just template "{{talos_dir}}/talosconfig.yaml.j2" "{{nodes_file}}" > "{{talos_dir}}/talosconfig"

[doc('Render Talos config for a node')]
render-config node:
    #!/usr/bin/env bash
    set -euo pipefail
    export TALOS_VERSION=$(yq '.talosVersion' "{{versions_file}}")
    export KUBERNETES_VERSION=$(yq '.kubernetesVersion' "{{versions_file}}")
    just template "{{talos_dir}}/machineconfig.yaml.j2" -D node={{node}} "{{nodes_file}}"

[doc('Diff rendered config against applied config on node')]
diff-config node="":
    #!/usr/bin/env bash
    set -euo pipefail
    read -r node ip _ <<< "$(just talos resolve-node "{{node}}" "Select node to diff")"
    just talos render-config "$node" | talosctl apply-config -n "$ip" -f /dev/stdin --dry-run

[doc('Apply Talos config to a node (auto-detects maintenance mode)')]
apply-node node="" *flags="":
    #!/usr/bin/env bash
    set -euo pipefail
    read -r node ip _ <<< "$(just talos resolve-node "{{node}}" "Select node to apply config")"
    insecure=$(just talos detect-insecure "$ip")
    just log info "Applying config to $node ($ip)..."
    just talos render-config "$node" | talosctl apply-config -n "$ip" -f /dev/stdin $insecure {{flags}}

[doc('Generate schematic ID from Talos factory')]
gen-schematic-id:
    @just template "{{talos_dir}}/schematic.yaml.j2" | \
        curl -sX POST --data-binary @- "https://factory.talos.dev/schematics" | jq -r '.id'

[doc('Download Talos machine image')]
download-image version schematic:
    #!/usr/bin/env bash
    set -euo pipefail
    schematic="{{schematic}}"
    short_schematic="${schematic:0:8}"
    output="{{talos_dir}}/talos-{{version}}-${short_schematic}.iso"
    just log info "Downloading Talos {{version}}..." schematic="{{schematic}}"
    curl -sfL --retry 5 --retry-delay 5 --retry-all-errors \
        -o "$output" \
        "https://factory.talos.dev/image/{{schematic}}/{{version}}/metal-amd64.iso"
    just log info "Downloaded" path="$output"

[doc('Verify etcd cluster health')]
check-etcd:
    #!/usr/bin/env bash
    set -euo pipefail
    just talos require-etcd-healthy
    just log info "etcd is healthy"

[doc('Show etcd members and status')]
etcd-status:
    #!/usr/bin/env bash
    set -euo pipefail
    cp_ip=$(just talos cp-ip)
    just log info "etcd members:"
    talosctl etcd members -n "$cp_ip"
    echo
    just log info "etcd status:"
    talosctl etcd status -n "$cp_ip"

[doc('Take an etcd snapshot (checks health first)')]
etcd-snapshot:
    #!/usr/bin/env bash
    set -euo pipefail
    just talos require-etcd-healthy
    cp_ip=$(just talos cp-ip)
    timestamp=$(date +%Y%m%d-%H%M%S)
    output="/tmp/etcd-backup-${timestamp}.snapshot"
    just log info "Taking etcd snapshot..."
    talosctl etcd snapshot -n "$cp_ip" "$output"
    just log info "Snapshot saved to $output"

[doc('Reboot a node')]
reboot-node node="":
    #!/usr/bin/env bash
    set -euo pipefail
    read -r node ip _ <<< "$(just talos resolve-node "{{node}}" "Select node to reboot")"
    just log info "Rebooting $node ($ip)..."
    talosctl -n "$ip" reboot

[doc('Shutdown a node')]
shutdown-node node="":
    #!/usr/bin/env bash
    set -euo pipefail
    read -r node ip _ <<< "$(just talos resolve-node "{{node}}" "Select node to shutdown")"
    just log info "Shutting down $node ($ip)..."
    talosctl -n "$ip" shutdown --force

[confirm("This will reset the node (cordon, drain, wipe disk, shutdown). Continue?")]
[doc('Reset a single node (checks etcd health first for CP nodes)')]
reset-node node="" *flags="":
    #!/usr/bin/env bash
    set -euo pipefail
    read -r node ip is_cp <<< "$(just talos resolve-node "{{node}}" "Select node to reset")"
    if [[ "$is_cp" == "true" ]]; then
        just talos require-etcd-healthy
    fi
    just log info "Resetting $node ($ip)..."
    talosctl reset -n "$ip" {{flags}}

[doc('Remove a node from Kubernetes')]
remove-node node="":
    #!/usr/bin/env bash
    set -euo pipefail
    read -r node _ _ <<< "$(just talos resolve-node "{{node}}" "Select node to remove")"
    just log info "Removing Kubernetes node $node..."
    kubectl delete node "$node" --ignore-not-found

[doc('Verify node health after maintenance (includes etcd for CP nodes)')]
verify-node node="":
    #!/usr/bin/env bash
    set -euo pipefail
    read -r node ip is_cp <<< "$(just talos resolve-node "{{node}}" "Select node to verify")"
    just log info "Kubernetes node status:"
    kubectl get node "$node"
    echo
    just log info "Talos version:"
    talosctl version -n "$ip" --short
    echo
    just log info "Disks:"
    talosctl get disks -n "$ip"
    if [[ "$is_cp" == "true" ]]; then
        echo
        just log info "etcd members:"
        talosctl etcd members -n "$ip"
        echo
        just log info "etcd status:"
        talosctl etcd status -n "$ip"
    fi

[doc('Upgrade Talos on a node')]
upgrade-node node="":
    #!/usr/bin/env bash
    set -euo pipefail
    read -r node ip _ <<< "$(just talos resolve-node "{{node}}" "Select node to upgrade")"
    image=$(just talos render-config "$node" | yq '.machine.install.image')
    just log info "Upgrading $node ($ip)..." image="$image"
    talosctl upgrade -n "$ip" --image "$image" --timeout=10m

[doc('Upgrade Kubernetes version')]
upgrade-k8s version:
    #!/usr/bin/env bash
    set -euo pipefail
    controller=$(just talos cp-ip)
    just log info "Upgrading Kubernetes to {{version}}..." controller="$controller"
    talosctl -n "$controller" upgrade-k8s --to {{version}}
