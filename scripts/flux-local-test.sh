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

FLUX_PATH="kubernetes/flux/cluster"

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

main() {
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

    log_info "Running flux-local test..."
    uvx flux-local test --enable-helm --all-namespaces --path "$FLUX_PATH"

    log_success "flux-local test completed successfully"
}

main "$@"
