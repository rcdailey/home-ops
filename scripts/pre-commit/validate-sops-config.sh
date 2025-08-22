#!/bin/bash
# scripts/validate-sops-config.sh
# Simple SOPS validation for Kubernetes applications

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Global variables
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Change to repo root for relative path operations
cd "$REPO_ROOT"

# Logging functions
log_error() {
    echo -e "${RED}❌ ERROR: $1${NC}" >&2
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_info() {
    echo -e "${YELLOW}ℹ INFO: $1${NC}"
}

# Extract app directory from a file path
get_app_directory() {
    local file="$1"

    # Extract app directory from kubernetes/apps/{namespace}/{app}/...
    if [[ "$file" =~ ^kubernetes/apps/([^/]+)/([^/]+)/ ]]; then
        local namespace="${BASH_REMATCH[1]}"
        local app="${BASH_REMATCH[2]}"
        echo "kubernetes/apps/${namespace}/${app}"
        return 0
    fi

    return 1
}

# Find the Kustomization that processes this app directory
find_kustomization_for_app() {
    local app_dir="$1"
    local ks_file="$app_dir/ks.yaml"

    # Check if ks.yaml exists in the app directory
    if [[ -f "$ks_file" ]]; then
        echo "$ks_file"
        return 0
    fi

    # Could extend this to check parent directories if needed
    return 1
}

# Validate SOPS file format
validate_sops_file() {
    local sops_file="$1"
    local failed=0

    log_info "Validating SOPS file: $sops_file"

    # Check file exists and is readable
    if [[ ! -f "$sops_file" ]]; then
        log_error "$sops_file: File does not exist"
        return 1
    fi

    # Check for sops metadata section
    if ! rg -q "^sops:" "$sops_file"; then
        log_error "$sops_file: Missing SOPS metadata section"
        failed=1
    fi

    # Check for age encryption
    if ! yq eval '.sops.age' "$sops_file" 2>/dev/null | rg -q "recipient"; then
        log_error "$sops_file: Missing age encryption configuration"
        failed=1
    fi

    # Check for encrypted_regex
    if ! yq eval '.sops.encrypted_regex' "$sops_file" 2>/dev/null | rg -q "stringData|data"; then
        log_error "$sops_file: Missing or invalid encrypted_regex pattern"
        failed=1
    fi

    return $failed
}

# Validate that Kustomization can decrypt SOPS files
validate_kustomization_decryption() {
    local ks_file="$1"
    local app_dir="$2"

    log_info "Checking decryption config in: $ks_file"

    if [[ ! -f "$ks_file" ]]; then
        log_error "$app_dir: No Kustomization found at $ks_file"
        return 1
    fi

    # Check if any Kustomization has SOPS decryption configured
    local has_sops_decryption=false

    # Look for decryption.provider: sops in any Kustomization
    if yq eval '.spec.decryption.provider' "$ks_file" 2>/dev/null | rg -q "sops"; then
        has_sops_decryption=true
    fi

    if [[ "$has_sops_decryption" == "false" ]]; then
        log_error "$app_dir: Has SOPS secrets but Kustomization missing SOPS decryption"
        log_info "Add to $ks_file: spec.decryption.provider: sops"
        return 1
    fi

    return 0
}

# Validate a single SOPS file and its app context
validate_sops_app() {
    local sops_file="$1"
    local failed=0

    # Get the app directory
    local app_dir
    if ! app_dir=$(get_app_directory "$sops_file"); then
        log_error "$sops_file: Cannot determine app directory from path"
        return 1
    fi

    log_info "Processing app: $app_dir"

    # Validate the SOPS file itself
    validate_sops_file "$sops_file" || failed=1

    # Find the Kustomization for this app
    local ks_file
    if ks_file=$(find_kustomization_for_app "$app_dir"); then
        validate_kustomization_decryption "$ks_file" "$app_dir" || failed=1
    else
        log_error "$app_dir: No Kustomization found (expected $app_dir/ks.yaml)"
        failed=1
    fi

    if [[ $failed -eq 0 ]]; then
        log_success "$app_dir: SOPS configuration valid"
    fi

    return $failed
}

# Main execution
main() {
    local changed_files=("$@")
    local total_failed=0

    if [[ ${#changed_files[@]} -eq 0 ]]; then
        log_info "No files provided for validation"
        return 0
    fi

    echo "🔍 Starting SOPS validation..."

    # Process each SOPS file
    for file in "${changed_files[@]}"; do
        # Only process .sops.yaml files
        if [[ "$file" =~ \.sops\.yaml$ ]]; then
            if ! validate_sops_app "$file"; then
                total_failed=1
            fi
            echo ""
        fi
    done

    if [[ $total_failed -eq 0 ]]; then
        log_success "All SOPS configurations validated successfully!"
    else
        log_error "Some SOPS validations failed!"
        exit 1
    fi
}

# Run main function with all arguments
main "$@"
