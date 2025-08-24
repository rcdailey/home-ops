#!/usr/bin/env bash

set -euo pipefail

# Check if we're in a TTY environment
if [[ -t 1 ]]; then
    # Colors for TTY output
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m' # No Color
else
    # No colors for non-TTY (pipes, CI, etc)
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
fi

# Default values
SCAN_ALL=false
FLUX_PATH="kubernetes/flux/cluster"

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Run flux-local test on modified/untracked files or entire repository.

OPTIONS:
    -a, --all       Scan entire repository instead of just changed files
    -h, --help      Show this help message

DESCRIPTION:
    By default, this script runs flux-local test on Kubernetes YAML files that are:
    - Modified (git status shows as modified)
    - Untracked (new files not yet added to git)

    With --all flag, it scans the entire kubernetes/ directory tree.

EXAMPLES:
    $0              # Test only changed files
    $0 --all        # Test entire repository
EOF
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

run_flux_local_test() {
    log_info "Running flux-local test..."
    uvx flux-local test --enable-helm --all-namespaces --path "$FLUX_PATH"
}

get_changed_files() {
    # Get all working changes: staged, unstaged (except deletions), and untracked YAML files
    {
        # Staged changes (excluding deletions)
        git diff --cached --name-status -- 'kubernetes/**/*.yaml' 'kubernetes/**/*.yml' 2>/dev/null | \
            awk '$1 != "D" {print $2}' || true

        # Unstaged changes (excluding deletions)
        git diff --name-status -- 'kubernetes/**/*.yaml' 'kubernetes/**/*.yml' 2>/dev/null | \
            awk '$1 != "D" {print $2}' || true

        # Untracked files
        git ls-files --others --exclude-standard -- 'kubernetes/**/*.yaml' 'kubernetes/**/*.yml' 2>/dev/null || true
    } | sort -u | grep -v '^$' || true
}

main() {
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -a|--all)
                SCAN_ALL=true
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done

    # Check if we're in a git repository
    if ! git rev-parse --git-dir >/dev/null 2>&1; then
        log_error "Not in a git repository"
        exit 1
    fi

    # Check if flux path exists
    if [[ ! -d "$FLUX_PATH" ]]; then
        log_error "Flux path '$FLUX_PATH' does not exist"
        exit 1
    fi

    if [[ "$SCAN_ALL" == "true" ]]; then
        log_info "Running flux-local test on entire repository..."
        run_flux_local_test
    else
        log_info "Checking for modified and untracked Kubernetes YAML files..."

        # Get list of changed files
        mapfile -t changed_files < <(get_changed_files)

        if [[ ${#changed_files[@]} -eq 0 ]]; then
            log_warning "No modified or untracked Kubernetes YAML files found"
            log_info "Use --all flag to test entire repository"
            exit 0
        fi

        log_info "Found ${#changed_files[@]} changed file(s):"
        printf '  %s\n' "${changed_files[@]}"

        # Run flux-local test
        run_flux_local_test
    fi

    log_success "flux-local test completed successfully"
}

main "$@"
