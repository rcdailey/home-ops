#!/usr/bin/env bash

# validate-vmrules.sh - Download and use vmalert to validate VMRule files
# Usage: scripts/validate-vmrules.sh [path-to-vmrules-directory]

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VMALERT_BINARY="${SCRIPT_DIR}/vmalert"

# Default VMRules directory
VMRULES_DIR="${1:-kubernetes/apps/observability/vmrules}"

# Function to print colored output
print_status() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Function to detect OS and architecture
detect_platform() {
    local os=""
    local arch=""

    case "$(uname -s)" in
        Linux*)  os="linux" ;;
        Darwin*) os="darwin" ;;
        CYGWIN*|MINGW*) os="windows" ;;
        *)
            print_status "$RED" "❌ Unsupported OS: $(uname -s)"
            exit 1
            ;;
    esac

    case "$(uname -m)" in
        x86_64|amd64) arch="amd64" ;;
        arm64|aarch64) arch="arm64" ;;
        armv7l) arch="arm" ;;
        i386|i686) arch="386" ;;
        *)
            print_status "$RED" "❌ Unsupported architecture: $(uname -m)"
            exit 1
            ;;
    esac

    echo "${os}-${arch}"
}

# Function to get latest VictoriaMetrics release
get_latest_release() {
    local latest_url="https://api.github.com/repos/VictoriaMetrics/VictoriaMetrics/releases/latest"

    if command -v curl >/dev/null 2>&1; then
        curl -s "$latest_url" | grep '"tag_name":' | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/'
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- "$latest_url" | grep '"tag_name":' | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/'
    else
        print_status "$RED" "❌ Neither curl nor wget found. Please install one of them."
        exit 1
    fi
}

# Function to download vmalert binary
download_vmalert() {
    local version=$1
    local platform=$2
    local filename="vmutils-${platform}-${version}.tar.gz"
    local download_url="https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/${version}/${filename}"

    print_status "$BLUE" "📥 Downloading vmutils ${version} for ${platform}..."

    if command -v curl >/dev/null 2>&1; then
        curl -L -o "/tmp/${filename}" "$download_url"
    elif command -v wget >/dev/null 2>&1; then
        wget -O "/tmp/${filename}" "$download_url"
    else
        print_status "$RED" "❌ Neither curl nor wget found."
        exit 1
    fi

    print_status "$BLUE" "📦 Extracting vmalert binary..."
    tar -xzf "/tmp/${filename}" -C /tmp

    # Move binary to script directory (the extracted binary is named vmalert-prod)
    mv "/tmp/vmalert-prod" "$VMALERT_BINARY"
    chmod +x "$VMALERT_BINARY"

    # Cleanup
    rm -f "/tmp/${filename}"

    print_status "$GREEN" "✅ vmalert downloaded successfully"
}

# Function to extract rules from VMRule CRD
extract_vmrule_spec() {
    local vmrule_file=$1
    local temp_file="/tmp/$(basename "$vmrule_file" .yaml)_rules.yaml"

    # Check if yq is available
    if ! command -v yq >/dev/null 2>&1; then
        print_status "$RED" "❌ yq is required to extract VMRule specs. Please install yq."
        exit 1
    fi

    # Extract the groups array from VMRule spec and create a valid Prometheus rules file
    yq eval '.spec' "$vmrule_file" > "$temp_file"

    echo "$temp_file"
}

# Function to validate VMRules
validate_vmrules() {
    local vmrules_dir=$1

    if [[ ! -d "$vmrules_dir" ]]; then
        print_status "$RED" "❌ VMRules directory not found: $vmrules_dir"
        exit 1
    fi

    # Find all YAML files in the directory
    local rule_files
    rule_files=$(find "$vmrules_dir" -name "*.yaml" -o -name "*.yml" | grep -v kustomization | sort)

    if [[ -z "$rule_files" ]]; then
        print_status "$YELLOW" "⚠️  No VMRule files found in $vmrules_dir"
        exit 0
    fi

    print_status "$BLUE" "🔍 Found VMRule files:"
    echo "$rule_files" | while read -r file; do
        echo "  - $file"
    done
    echo

    # Validate each file
    local validation_failed=false
    local temp_files=()

    for rule_file in $rule_files; do
        print_status "$BLUE" "🔍 Validating: $rule_file"

        # Extract VMRule spec to temporary file
        local temp_rule_file
        temp_rule_file=$(extract_vmrule_spec "$rule_file")
        temp_files+=("$temp_rule_file")

        # Run vmalert with -dryRun flag on the extracted rules
        if "$VMALERT_BINARY" -rule="$temp_rule_file" -dryRun >/dev/null 2>&1; then
            print_status "$GREEN" "✅ $rule_file - VALID"
        else
            print_status "$RED" "❌ $rule_file - INVALID"
            # Show the actual validation error
            "$VMALERT_BINARY" -rule="$temp_rule_file" -dryRun 2>&1 | grep -E "(error|fail|invalid)" || true
            validation_failed=true
        fi
        echo
    done

    # Cleanup temporary files
    for temp_file in "${temp_files[@]}"; do
        rm -f "$temp_file" 2>/dev/null || true
    done

    if [[ "$validation_failed" == true ]]; then
        print_status "$RED" "❌ VMRule validation failed!"
        exit 1
    else
        print_status "$GREEN" "🎉 All VMRules are valid!"
    fi
}

# Main execution
main() {
    print_status "$BLUE" "🚀 VMRule Validation Script"
    echo

    # Check if vmalert binary exists
    if [[ ! -f "$VMALERT_BINARY" ]]; then
        print_status "$YELLOW" "📥 vmalert binary not found. Downloading..."

        local platform
        platform=$(detect_platform)

        local latest_version
        latest_version=$(get_latest_release)

        if [[ -z "$latest_version" ]]; then
            print_status "$RED" "❌ Failed to get latest VictoriaMetrics release"
            exit 1
        fi

        download_vmalert "$latest_version" "$platform"
        echo
    else
        print_status "$GREEN" "✅ Found existing vmalert binary"
        # Show version info
        print_status "$BLUE" "ℹ️  Version: $("$VMALERT_BINARY" -version 2>&1 | head -n1 || echo "Unknown")"
        echo
    fi

    # Validate VMRules
    validate_vmrules "$VMRULES_DIR"
}

# Help text
show_help() {
    cat << EOF
VMRule Validation Script

USAGE:
    $0 [OPTIONS] [VMRULES_DIRECTORY]

OPTIONS:
    -h, --help          Show this help message
    --clean             Remove downloaded vmalert binary and exit

EXAMPLES:
    # Validate default VMRules directory
    $0

    # Validate specific directory
    $0 path/to/vmrules

    # Clean up downloaded binary
    $0 --clean

DESCRIPTION:
    This script downloads the latest vmalert binary (if not already present)
    and validates all VMRule YAML files in the specified directory using
    vmalert's -dryRun flag.

    The vmalert binary is downloaded to the scripts directory and ignored
    by git via scripts/.gitignore.

EOF
}

# Handle command line arguments
case "${1:-}" in
    -h|--help)
        show_help
        exit 0
        ;;
    --clean)
        if [[ -f "$VMALERT_BINARY" ]]; then
            rm -f "$VMALERT_BINARY"
            print_status "$GREEN" "✅ Cleaned up vmalert binary"
        else
            print_status "$YELLOW" "⚠️  No vmalert binary to clean"
        fi
        exit 0
        ;;
    -*)
        print_status "$RED" "❌ Unknown option: $1"
        echo "Use --help for usage information"
        exit 1
        ;;
esac

# Run main function
main
