#!/bin/bash

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

check_dependency() {
    local tool="$1"
    local install_hint="$2"

    if ! command -v "$tool" >/dev/null 2>&1; then
        echo -e "${RED}❌ Missing dependency: ${tool}${NC}"
        echo -e "${YELLOW}💡 Install with: ${install_hint}${NC}"
        return 1
    fi
    return 0
}

check_all_dependencies() {
    local missing=0

    echo -e "${BLUE}🔍 Checking pre-commit dependencies...${NC}"

    # Check each required tool
    check_dependency "kustomize" "brew install kustomize" || missing=1
    check_dependency "yq" "brew install yq" || missing=1
    check_dependency "kubectl" "brew install kubectl" || missing=1
    check_dependency "sops" "brew install sops" || missing=1

    if [[ $missing -eq 1 ]]; then
        echo ""
        echo -e "${RED}📋 Some dependencies are missing. Please install them and try again.${NC}"
        echo -e "${YELLOW}💡 You can also install all at once: brew install kustomize yq kubectl sops${NC}"
        return 1
    fi

    echo -e "${GREEN}✅ All dependencies are available${NC}"
    return 0
}

# If called directly, check all dependencies
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    check_all_dependencies
fi
