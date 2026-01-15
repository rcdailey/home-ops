set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

bootstrap_dir := source_directory()
kubernetes_dir := parent_directory(source_directory()) / "kubernetes"
talos_dir := parent_directory(source_directory()) / "talos"
nodes_file := talos_dir / "nodes.yaml"

[private]
default:
    @just --list bootstrap

[doc('Full Talos cluster bootstrap (fresh install)')]
talos: talos-apply talos-bootstrap talos-kubeconfig
    @just log info "Talos cluster bootstrap complete"

[doc('Apply Talos config to all nodes')]
[private]
talos-apply:
    #!/usr/bin/env bash
    set -euo pipefail
    for node in $(yq '.nodes | keys | .[]' "{{nodes_file}}"); do
        ip=$(yq ".nodes.$node.ip" "{{nodes_file}}")
        just log info "Applying config to $node ($ip)..."
        if ! output=$(just talos render-config "$node" | talosctl apply-config -n "$ip" -f /dev/stdin --insecure 2>&1); then
            if [[ "$output" == *"certificate required"* ]]; then
                just log info "Talos already configured, skipping" node="$node"
                continue
            fi
            just log error "Failed to apply config" node="$node" output="$output"
            exit 1
        fi
    done

[doc('Bootstrap Kubernetes on first controller')]
[private]
talos-bootstrap:
    #!/usr/bin/env bash
    set -euo pipefail
    controller=$(yq '.nodes | to_entries | map(select(.value.controller == true)) | .[0].value.ip' "{{nodes_file}}")
    until output=$(talosctl -n "$controller" bootstrap 2>&1 || true) && [[ "$output" == *"AlreadyExists"* ]]; do
        just log info "Kubernetes bootstrap in progress, retrying in 5s..."
        sleep 5
    done

[doc('Fetch kubeconfig from cluster')]
[private]
talos-kubeconfig:
    #!/usr/bin/env bash
    set -euo pipefail
    controller=$(yq '.nodes | to_entries | map(select(.value.controller == true)) | .[0].value.ip' "{{nodes_file}}")
    talosctl kubeconfig -n "$controller" -f --force-context-name home-ops "{{parent_directory(source_directory())}}"

[doc('Full apps bootstrap sequence')]
apps: wait namespaces resources crds helm-releases
    @just log info "Apps bootstrap complete - Flux is now syncing"

[doc('Wait for nodes to be available')]
[private]
wait:
    #!/usr/bin/env bash
    set -euo pipefail
    just log info "Waiting for nodes..."
    if kubectl wait nodes --for=condition=Ready=True --all --timeout=10s &>/dev/null; then
        just log info "Nodes ready"
        exit 0
    fi
    until kubectl wait nodes --for=condition=Ready=False --all --timeout=10s &>/dev/null; do
        just log info "Nodes not available, retrying in 5s..."
        sleep 5
    done

[doc('Apply namespaces from kubernetes/apps')]
[private]
namespaces:
    #!/usr/bin/env bash
    set -euo pipefail
    just log info "Applying namespaces..."
    for dir in "{{kubernetes_dir}}/apps"/*/; do
        ns=$(basename "$dir")
        if ! kustomize build "$dir" | yq ea -e 'select(.kind == "Namespace")' 2>/dev/null | \
            kubectl apply --server-side -f - 2>/dev/null; then
            # Fallback: create bare namespace if no Namespace resource in kustomization
            kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply --server-side -f -
        fi
        just log info "Applied namespace" namespace="$ns"
    done

[doc('Apply bootstrap resources (Infisical credentials)')]
resources:
    #!/usr/bin/env bash
    set -euo pipefail

    if kubectl get secret infisical-credentials -n kube-system &>/dev/null; then
        flux_labels=$(kubectl get secret infisical-credentials -n kube-system -o jsonpath='{.metadata.labels.kustomize\.toolkit\.fluxcd\.io/name}')
        if [[ -n "$flux_labels" ]]; then
            gum style --foreground 212 "Secret 'infisical-credentials' exists with Flux ownership"
            if ! gum confirm "Remove Flux labels and replace?"; then
                gum style --foreground 196 "Aborted."
                exit 1
            fi
            kubectl label secret infisical-credentials -n kube-system \
                kustomize.toolkit.fluxcd.io/name- \
                kustomize.toolkit.fluxcd.io/namespace- \
                app.kubernetes.io/name-
            gum style --foreground 82 "Flux labels removed"
        fi
    fi

    just log info "Applying bootstrap resources..."
    just template "{{bootstrap_dir}}/resources.yaml.j2" | kubectl apply --server-side -f -

[doc('Apply CRDs')]
[private]
crds:
    #!/usr/bin/env bash
    set -euo pipefail
    just log info "Applying CRDs..."
    crds=(
        # renovate: datasource=github-releases depName=kubernetes-sigs/external-dns
        "https://raw.githubusercontent.com/kubernetes-sigs/external-dns/refs/tags/v0.20.0/config/crd/standard/dnsendpoints.externaldns.k8s.io.yaml"
        # renovate: datasource=github-releases depName=kubernetes-sigs/gateway-api
        "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.4.0/experimental-install.yaml"
        # renovate: datasource=github-releases depName=prometheus-operator/prometheus-operator
        "https://github.com/prometheus-operator/prometheus-operator/releases/download/v0.87.1/stripped-down-crds.yaml"
    )
    for crd in "${crds[@]}"; do
        kubectl apply --server-side -f "$crd"
        just log info "Applied CRD" url="$crd"
    done

[doc('Sync Helm releases via helmfile')]
[private]
helm-releases:
    @just log info "Syncing Helm releases..."
    @helmfile --file "{{bootstrap_dir}}/helmfile.yaml" sync --hide-notes
