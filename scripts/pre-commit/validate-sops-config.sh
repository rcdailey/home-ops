#!/bin/bash
# scripts/validate-sops-config.sh
# Validates SOPS decryption configuration for Kubernetes applications

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

# Extract unique app directories from changed files
get_app_directories() {
    local changed_files=("$@")
    local app_dirs=()

    for file in "${changed_files[@]}"; do
        # Extract app directory from kubernetes/apps/{namespace}/{app}/...
        if [[ "$file" =~ ^kubernetes/apps/([^/]+)/([^/]+)/ ]]; then
            local namespace="${BASH_REMATCH[1]}"
            local app="${BASH_REMATCH[2]}"
            local app_dir="kubernetes/apps/${namespace}/${app}"

            # Add to array if not already present
            if [[ ! " ${app_dirs[*]} " =~ " ${app_dir} " ]]; then
                app_dirs+=("$app_dir")
            fi
        fi
    done

    printf '%s\n' "${app_dirs[@]}"
}

# Check if directory has SOPS encrypted files
has_sops_secrets() {
    local app_dir="$1"
    local secrets_dir="$app_dir/secrets"

    [[ -d "$secrets_dir" ]] && find "$secrets_dir" -name "*.sops.yaml" -type f | grep -q .
}

# Validate SOPS decryption configuration exists
validate_sops_decryption_config() {
    local app_dir="$1"
    local ks_file="$app_dir/ks.yaml"

    if [[ ! -f "$ks_file" ]]; then
        log_error "$app_dir: Missing ks.yaml file"
        return 1
    fi

    # Check if any Kustomization has SOPS decryption configured
    local decryption_providers=$(yq eval '.spec.decryption.provider' "$ks_file" 2>/dev/null | grep -v '^null$' | grep -v '^---$' | grep -v '^$')

    if ! echo "$decryption_providers" | grep -q "sops"; then
        log_error "$app_dir: Has SOPS secrets but missing decryption configuration in ks.yaml"
        log_info "Add decryption config: spec.decryption.provider: sops, spec.decryption.secretRef.name: sops-age"
        return 1
    fi

    return 0
}

# Validate two-Kustomization pattern for apps with secrets
validate_kustomization_pattern() {
    local app_dir="$1"
    local ks_file="$app_dir/ks.yaml"

    # Count Kustomizations in ks.yaml
    local kustomization_count=$(yq eval 'select(.kind == "Kustomization")' "$ks_file" 2>/dev/null | yq eval '.metadata.name' - | wc -l)

    if [[ $kustomization_count -lt 2 ]]; then
        log_error "$app_dir: Has SOPS secrets but uses single Kustomization (should use two-Kustomization pattern)"
        log_info "Pattern: one Kustomization for secrets/ with SOPS decryption, one for app/ with dependsOn"
        return 1
    fi

    return 0
}

# Validate path alignment between Kustomizations and directories
validate_path_alignment() {
    local app_dir="$1"
    local ks_file="$app_dir/ks.yaml"
    local failed=0

    # Extract all Kustomization paths and validate they exist
    while IFS= read -r path; do
        [[ -z "$path" || "$path" == "null" || "$path" == "---" ]] && continue

        # Convert relative path to absolute for checking
        local full_path="$REPO_ROOT/$path"

        if [[ ! -d "$full_path" ]]; then
            log_error "$app_dir: Kustomization path '$path' does not exist"
            failed=1
        elif [[ ! -f "$full_path/kustomization.yaml" ]]; then
            log_error "$app_dir: Path '$path' missing kustomization.yaml"
            failed=1
        fi
    done < <(yq eval 'select(.kind == "Kustomization") | .spec.path // empty' "$ks_file" 2>/dev/null | grep -v '^$')

    return $failed
}

# Validate dependency chain between secrets and app Kustomizations
validate_dependency_chain() {
    local app_dir="$1"
    local ks_file="$app_dir/ks.yaml"
    local app_name=$(basename "$app_dir")

    # Check if app Kustomization depends on secrets Kustomization
    local has_dependency=false

    # Look for dependsOn pointing to secrets Kustomization
    if yq eval 'select(.kind == "Kustomization") | .spec.dependsOn[]?.name' "$ks_file" 2>/dev/null | grep -q "${app_name}-secrets"; then
        has_dependency=true
    fi

    if [[ "$has_dependency" == "false" ]]; then
        log_error "$app_dir: App Kustomization missing dependsOn: ${app_name}-secrets"
        log_info "Add: spec.dependsOn[].name: ${app_name}-secrets"
        return 1
    fi

    return 0
}

# Validate naming conventions
validate_naming_conventions() {
    local app_dir="$1"
    local ks_file="$app_dir/ks.yaml"
    local app_name=$(basename "$app_dir")
    local failed=0

    # Check for expected Kustomization names
    local kustomization_names=()
    while IFS= read -r name; do
        [[ -z "$name" || "$name" == "null" ]] && continue
        kustomization_names+=("$name")
    done < <(yq eval 'select(.kind == "Kustomization") | .metadata.name' "$ks_file" 2>/dev/null)

    local has_secrets_kustomization=false
    local has_app_kustomization=false

    for name in "${kustomization_names[@]}"; do
        if [[ "$name" == "${app_name}-secrets" ]]; then
            has_secrets_kustomization=true
        elif [[ "$name" == "${app_name}-app" ]]; then
            has_app_kustomization=true
        fi
    done

    if [[ "$has_secrets_kustomization" == "false" ]]; then
        log_error "$app_dir: Missing secrets Kustomization named '${app_name}-secrets'"
        failed=1
    fi

    if [[ "$has_app_kustomization" == "false" ]]; then
        log_error "$app_dir: Missing app Kustomization named '${app_name}-app'"
        failed=1
    fi

    return $failed
}

# Validate SOPS file format
validate_sops_file_format() {
    local app_dir="$1"
    local secrets_dir="$app_dir/secrets"
    local failed=0

    if [[ ! -d "$secrets_dir" ]]; then
        return 0
    fi

    while IFS= read -r sops_file; do
        [[ -z "$sops_file" ]] && continue

        # Check for sops metadata section
        if ! grep -q "^sops:" "$sops_file"; then
            log_error "$sops_file: Missing SOPS metadata section"
            failed=1
        fi

        # Check for age encryption
        if ! yq eval '.sops.age' "$sops_file" 2>/dev/null | grep -q "recipient"; then
            log_error "$sops_file: Missing age encryption configuration"
            failed=1
        fi

        # Check for encrypted_regex
        if ! yq eval '.sops.encrypted_regex' "$sops_file" 2>/dev/null | grep -q "stringData\|data"; then
            log_error "$sops_file: Missing or invalid encrypted_regex pattern"
            failed=1
        fi

    done < <(find "$secrets_dir" -name "*.sops.yaml" -type f 2>/dev/null)

    return $failed
}

# Validate a single app directory
validate_app() {
    local app_dir="$1"
    local failed=0

    log_info "Validating $app_dir"

    # Skip apps without SOPS secrets
    if ! has_sops_secrets "$app_dir"; then
        log_info "$app_dir: No SOPS secrets found, skipping validation"
        return 0
    fi

    # Run all validations
    validate_sops_decryption_config "$app_dir" || failed=1
    validate_kustomization_pattern "$app_dir" || failed=1
    validate_path_alignment "$app_dir" || failed=1
    validate_dependency_chain "$app_dir" || failed=1
    validate_naming_conventions "$app_dir" || failed=1
    validate_sops_file_format "$app_dir" || failed=1

    if [[ $failed -eq 0 ]]; then
        log_success "$app_dir: SOPS configuration valid"
    fi

    return $failed
}

# Main execution
main() {
    local changed_files=("$@")

    if [[ ${#changed_files[@]} -eq 0 ]]; then
        log_info "No files provided for validation"
        return 0
    fi

    echo "Starting SOPS configuration validation..."

    # Get unique app directories from changed files
    local app_dirs=()
    while IFS= read -r app_dir; do
        [[ -n "$app_dir" ]] && app_dirs+=("$app_dir")
    done < <(get_app_directories "${changed_files[@]}")

    if [[ ${#app_dirs[@]} -eq 0 ]]; then
        log_info "No app directories found in changed files"
        return 0
    fi

    local total_failed=0

    # Validate each app directory
    for app_dir in "${app_dirs[@]}"; do
        if [[ -d "$app_dir" ]]; then
            validate_app "$app_dir" || total_failed=1
        else
            log_error "App directory not found: $app_dir"
            total_failed=1
        fi
    done

    echo ""
    if [[ $total_failed -eq 0 ]]; then
        log_success "All SOPS configurations validated successfully!"
    else
        log_error "Some SOPS configuration validations failed!"
        exit 1
    fi
}

# Run main function with all arguments
main "$@"
