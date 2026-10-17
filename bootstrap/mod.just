set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

bootstrap_dir := source_directory()
kubernetes_dir := parent_directory(source_directory()) / "kubernetes"
topf_file := parent_directory(source_directory()) / "talos" / "topf.yaml"

[private]
default:
    @just --list bootstrap

[doc('Full Talos cluster bootstrap (fresh install)')]
talos: talos-apply kubeconfig
    @just log info "Talos cluster bootstrap complete"

[doc('Apply Talos config to all nodes and bootstrap etcd')]
[private]
talos-apply:
    @just talos topf apply --auto-bootstrap

[doc('Fetch kubeconfig from cluster')]
kubeconfig:
    #!/usr/bin/env bash
    set -euo pipefail
    controller=$(yq '[.nodes[] | select(.role == "control-plane")][0].ip' "{{topf_file}}")
    talosctl kubeconfig -n "$controller" -f --force-context-name home-ops "{{parent_directory(source_directory())}}"

[doc('Full apps bootstrap sequence')]
apps: wait namespaces resources crds helm-releases flux-instance
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

[doc('Apply the Flux instance')]
[private]
flux-instance:
    @just log info "Applying Flux instance..."
    @kubectl apply --server-side --namespace flux-system \
        --filename "{{kubernetes_dir}}/apps/flux-system/flux-instance/fluxinstance.yaml"
