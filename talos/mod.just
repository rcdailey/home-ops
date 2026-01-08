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

[doc('List available Talos nodes with IPs')]
list-nodes:
    #!/usr/bin/env bash
    set -euo pipefail
    nodes_file="{{nodes_file}}"
    for node in $(yq '.nodes | keys | .[]' "$nodes_file"); do
        ip=$(yq ".nodes.$node.ip" "$nodes_file")
        controller=$(yq ".nodes.$node.controller" "$nodes_file")
        role=$([[ "$controller" == "true" ]] && echo "control-plane" || echo "worker")
        echo "$node ($ip) [$role]"
    done

[doc('Template a file with Infisical secrets')]
[private]
template file *args:
    infisical run --env=prod --path=/bootstrap -- minijinja-cli "{{file}}" {{args}} "{{nodes_file}}"

[doc('Render Talos config for a node')]
render-config node:
    #!/usr/bin/env bash
    set -euo pipefail
    # Export versions from talenv.yaml (managed by renovate)
    export TALOS_VERSION=$(yq '.talosVersion' "{{versions_file}}")
    export KUBERNETES_VERSION=$(yq '.kubernetesVersion' "{{versions_file}}")
    just talos::template "{{talos_dir}}/machineconfig.yaml.j2" -D node={{node}}

[doc('Apply Talos config to a node')]
apply-node node="":
    #!/usr/bin/env bash
    set -euo pipefail
    node="{{node}}"
    if [ -z "$node" ]; then
        node=$(just talos::select-node "Select node to apply config")
    fi
    ip=$(yq ".nodes.$node.ip" "{{nodes_file}}")
    echo "Applying config to $node ($ip)..."
    just talos::render-config "$node" | talosctl apply-config -n "$ip" -f /dev/stdin

[doc('Generate schematic ID from Talos factory')]
gen-schematic-id:
    @just talos::template "{{talos_dir}}/schematic.yaml.j2" | \
        curl -sX POST --data-binary @- "https://factory.talos.dev/schematics" | jq -r '.id'

[doc('Upgrade Talos on a node')]
upgrade-node node="":
    #!/usr/bin/env bash
    set -euo pipefail
    node="{{node}}"
    if [ -z "$node" ]; then
        node=$(just talos::select-node "Select node to upgrade")
    fi
    ip=$(yq ".nodes.$node.ip" "{{nodes_file}}")
    image=$(just talos::render-config "$node" | yq '.machine.install.image')
    echo "Upgrading $node ($ip) with image: $image"
    talosctl upgrade -n "$ip" --image "$image" --timeout=10m

[doc('Upgrade Kubernetes version')]
upgrade-k8s version:
    #!/usr/bin/env bash
    set -euo pipefail
    controller=$(yq '.nodes | to_entries | map(select(.value.controller == true)) | .[0].value.ip' "{{nodes_file}}")
    echo "Upgrading Kubernetes to {{version}} via $controller"
    talosctl -n "$controller" upgrade-k8s --to {{version}}

[confirm("This will destroy your cluster and reset nodes to maintenance mode. Continue?")]
[doc('Reset nodes back to maintenance mode')]
reset:
    #!/usr/bin/env bash
    set -euo pipefail
    for node in $(yq '.nodes | keys | .[]' "{{nodes_file}}"); do
        ip=$(yq ".nodes.$node.ip" "{{nodes_file}}")
        echo "Resetting $node ($ip)..."
        talosctl reset -n "$ip" --reboot --system-labels-to-wipe STATE --system-labels-to-wipe EPHEMERAL --graceful=false --wait=false || true
    done
