set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

talos_dir := source_directory()
nodes_file := talos_dir / "nodes.yaml"
versions_file := talos_dir / "talenv.yaml"

[private]
default:
    @just --list talos

# Interactive node selection helper
[private]
select-node prompt="Select node":
    @yq '.nodes | keys | .[]' "{{nodes_file}}" | fzf --prompt="{{prompt}}: "

[doc('Initialize talosconfig from Infisical secrets')]
init-config:
    @just template "{{talos_dir}}/talosconfig.yaml.j2" "{{nodes_file}}" > "{{talos_dir}}/talosconfig"

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
    node="{{node}}"
    if [ -z "$node" ]; then
        node=$(just talos select-node "Select node to diff")
    fi
    ip=$(yq ".nodes.$node.ip" "{{nodes_file}}")
    just talos render-config "$node" | talosctl apply-config -n "$ip" -f /dev/stdin --dry-run

[doc('Apply Talos config to a node')]
apply-node node="":
    #!/usr/bin/env bash
    set -euo pipefail
    node="{{node}}"
    if [ -z "$node" ]; then
        node=$(just talos select-node "Select node to apply config")
    fi
    ip=$(yq ".nodes.$node.ip" "{{nodes_file}}")
    just log info "Applying config to $node ($ip)..."
    just talos render-config "$node" | talosctl apply-config -n "$ip" -f /dev/stdin

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

[doc('Reboot a node')]
reboot-node node="":
    #!/usr/bin/env bash
    set -euo pipefail
    node="{{node}}"
    if [ -z "$node" ]; then
        node=$(just talos select-node "Select node to reboot")
    fi
    ip=$(yq ".nodes.$node.ip" "{{nodes_file}}")
    just log info "Rebooting $node ($ip)..."
    talosctl -n "$ip" reboot

[doc('Shutdown a node')]
shutdown-node node="":
    #!/usr/bin/env bash
    set -euo pipefail
    node="{{node}}"
    if [ -z "$node" ]; then
        node=$(just talos select-node "Select node to shutdown")
    fi
    ip=$(yq ".nodes.$node.ip" "{{nodes_file}}")
    just log info "Shutting down $node ($ip)..."
    talosctl -n "$ip" shutdown --force

[doc('Upgrade Talos on a node')]
upgrade-node node="":
    #!/usr/bin/env bash
    set -euo pipefail
    node="{{node}}"
    if [ -z "$node" ]; then
        node=$(just talos select-node "Select node to upgrade")
    fi
    ip=$(yq ".nodes.$node.ip" "{{nodes_file}}")
    image=$(just talos render-config "$node" | yq '.machine.install.image')
    just log info "Upgrading $node ($ip)..." image="$image"
    talosctl upgrade -n "$ip" --image "$image" --timeout=10m

[doc('Upgrade Kubernetes version')]
upgrade-k8s version:
    #!/usr/bin/env bash
    set -euo pipefail
    controller=$(yq '.nodes | to_entries | map(select(.value.controller == true)) | .[0].value.ip' "{{nodes_file}}")
    just log info "Upgrading Kubernetes to {{version}}..." controller="$controller"
    talosctl -n "$controller" upgrade-k8s --to {{version}}

[confirm("This will destroy your cluster and reset nodes to maintenance mode. Continue?")]
[doc('Reset nodes back to maintenance mode')]
reset:
    #!/usr/bin/env bash
    set -euo pipefail
    for node in $(yq '.nodes | keys | .[]' "{{nodes_file}}"); do
        ip=$(yq ".nodes.$node.ip" "{{nodes_file}}")
        just log info "Resetting $node ($ip)..."
        talosctl reset -n "$ip" --reboot --system-labels-to-wipe STATE --system-labels-to-wipe EPHEMERAL --graceful=false --wait=false || true
    done
