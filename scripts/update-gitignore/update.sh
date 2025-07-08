#!/bin/bash

# Update .gitignore by concatenating custom patterns and gitignore.io templates
# This script generates .gitignore from component files in scripts/update-gitignore/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
GITIGNORE_FILE="$REPO_ROOT/.gitignore"

# Function to validate gitignore.io API is reachable
validate_api() {
    if ! curl -sf "https://www.toptal.com/developers/gitignore/api/list" >/dev/null; then
        echo "ERROR: Cannot reach gitignore.io API"
        exit 1
    fi
}

# Function to generate gitignore templates from gitignore.io
generate_gitignore() {
    local templates="$1"
    local response
    if ! response=$(curl -sf "https://www.toptal.com/developers/gitignore/api/${templates}" 2>&1); then
        echo "ERROR: Failed to generate templates for: $templates"
        echo "   This usually means one or more template names are invalid."
        exit 1
    fi
    echo "$response"
}

# Function to extract templates from templates.txt (ignoring comments and empty lines)
get_templates() {
    if [[ -f "$SCRIPT_DIR/templates.txt" ]]; then
        grep -v '^#' "$SCRIPT_DIR/templates.txt" | grep -v '^$' | tr '\n' ',' | sed 's/,$//'
    fi
}

# Function to write header/footer
write_header() {
    cat << 'EOF'
# =============================================================================
# GENERATED FILE - DO NOT EDIT DIRECTLY
# =============================================================================
# This .gitignore file is automatically generated. To make changes:
#
# 1. Edit custom patterns in: scripts/update-gitignore/custom/*.gitignore
# 2. Edit template list in: scripts/update-gitignore/templates.txt
# 3. Regenerate with: task scripts:gitignore:update
#
# =============================================================================
EOF
}

write_footer() {
    cat << 'EOF'
# =============================================================================
# END GENERATED FILE
# =============================================================================
EOF
}

main() {
    echo "Generating .gitignore from component files..."

    # Validate API is reachable first
    validate_api

    # Create temporary file
    local temp_file
    temp_file=$(mktemp)

    # Write header
    write_header > "$temp_file"
    echo "" >> "$temp_file"

    # Add custom gitignore files in sorted order from custom/ directory
    if ls "$SCRIPT_DIR/custom"/*.gitignore &> /dev/null; then
        echo "Adding custom patterns..."
        for gitignore_file in "$SCRIPT_DIR/custom"/*.gitignore; do
            echo "   - $(basename "$gitignore_file")"
            echo "" >> "$temp_file"
            echo "# From: custom/$(basename "$gitignore_file")" >> "$temp_file"
            cat "$gitignore_file" >> "$temp_file"
            echo "" >> "$temp_file"
        done
    fi

    # Add gitignore.io templates
    local templates
    templates=$(get_templates)

    if [[ -n "$templates" ]]; then
        echo "Adding gitignore.io templates..."
        echo "   - Templates: $templates"
        echo "" >> "$temp_file"
        echo "# From: gitignore.io templates ($templates)" >> "$temp_file"
        generate_gitignore "$templates" >> "$temp_file"
        echo "" >> "$temp_file"
    fi

    # Write footer
    write_footer >> "$temp_file"

    # Replace original file
    mv "$temp_file" "$GITIGNORE_FILE"

    echo ".gitignore updated successfully!"
    echo "Location: $GITIGNORE_FILE"
    echo "Total lines: $(wc -l < "$GITIGNORE_FILE")"
}

main "$@"
