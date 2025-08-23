#!/bin/bash
# scripts/validate-sops-k8s.sh
# Validates Kubernetes manifests with SOPS decryption and template variable support

set -euo pipefail

# Global variables for caching
TEMPLATE_VARS=""

# One-time decrypt of template variables (expensive operation)
load_template_vars() {
    if [[ -z "$TEMPLATE_VARS" ]]; then
        echo "INFO - Loading template variables from cluster-secrets..."

        # Find the repository root by looking for the cluster-secrets file
        local repo_root=""
        local current_dir="$(pwd)"

        while [[ "$current_dir" != "/" ]]; do
            if [[ -f "$current_dir/kubernetes/components/common/sops/cluster-secrets.sops.yaml" ]]; then
                repo_root="$current_dir"
                break
            fi
            current_dir="$(dirname "$current_dir")"
        done

        if [[ -z "$repo_root" ]]; then
            echo "ERROR - Could not find cluster-secrets.sops.yaml in repository"
            exit 1
        fi

        TEMPLATE_VARS=$(sops -d "$repo_root/kubernetes/components/common/sops/cluster-secrets.sops.yaml" | yq eval '.stringData // .data' - -o json)
    fi
}

# Process a single file for validation
validate_manifest() {
    local file="$1"

    # Skip kustomization files as they're not Kubernetes resources
    if [[ "$file" == *"kustomization.yaml" ]] || [[ "$file" == *"values.yaml" ]]; then
        echo "INFO - Skipping $file (not a Kubernetes resource)"
        return 0
    fi

    echo "INFO - Validating $file"

    # Handle SOPS encrypted files (pattern from research)
    if grep -q "sops:" "$file"; then
        echo "  Decrypting SOPS file..."
        sops --decrypt "$file" | kubectl apply --dry-run=server --validate=true -f -
        local kubectl_exit_code=${PIPESTATUS[1]}
    else
        # Handle template variables in regular files
        if grep -q '\${' "$file"; then
            echo "  Processing template variables..."

            # Export template variables as environment variables for envsubst
            while IFS= read -r line; do
                if [[ -n "$line" ]]; then
                    local key=$(echo "$line" | jq -r '.key')
                    local value=$(echo "$line" | jq -r '.value')
                    export "$key"="$value"
                fi
            done <<< "$(echo "$TEMPLATE_VARS" | jq -r 'to_entries[] | @json')"

            # Use envsubst for template substitution, but handle the special ${SECRET_DOMAIN/./-} pattern first
            local processed_content=$(cat "$file")

            # Handle ${SECRET_DOMAIN/./-} pattern manually since envsubst doesn't support it
            if grep -q '\${SECRET_DOMAIN/\.\/-}' "$file"; then
                local domain_with_dash=$(echo "${SECRET_DOMAIN}" | sed 's/\./-/g')
                processed_content=$(echo "$processed_content" | sed "s/\${SECRET_DOMAIN\/\.\/-}/${domain_with_dash}/g")
            fi

            # Use envsubst for standard ${VAR} patterns
            processed_content=$(echo "$processed_content" | envsubst)

            # Validate processed content
            echo "$processed_content" | kubectl apply --dry-run=server --validate=true -f -
            local kubectl_exit_code=${PIPESTATUS[1]}
        else
            # Regular file without templates or encryption
            kubectl apply --dry-run=server --validate=true -f "$file"
            local kubectl_exit_code=$?
        fi
    fi

    if [[ $kubectl_exit_code -eq 0 ]]; then
        echo "  ✅ Valid"
    else
        echo "  ❌ Invalid"
        return 1
    fi
}

# Check Kubernetes connectivity
check_kubectl_connection() {
    echo "INFO - Checking Kubernetes cluster connectivity..."

    if ! command -v kubectl >/dev/null 2>&1; then
        echo "ERROR - kubectl command not found"
        exit 1
    fi

    if ! kubectl cluster-info >/dev/null 2>&1; then
        echo "ERROR - Cannot connect to Kubernetes cluster"
        echo "       Ensure kubeconfig is properly configured and cluster is accessible"
        exit 1
    fi

    echo "INFO - Kubernetes cluster connection verified"
}

# Main execution
main() {
    echo "Starting Kubernetes manifest validation..."

    # Check cluster connectivity before proceeding
    check_kubectl_connection

    # Load template variables once
    load_template_vars

    local failed=0

    # Process each file provided as argument
    for file in "$@"; do
        if [[ -f "$file" ]]; then
            validate_manifest "$file" || failed=1
        else
            echo "WARNING - File not found: $file"
        fi
    done

    if [[ $failed -eq 0 ]]; then
        echo "✅ All manifests validated successfully!"
    else
        echo "❌ Some validations failed!"
        exit 1
    fi
}

# Run main function with all arguments
main "$@"
