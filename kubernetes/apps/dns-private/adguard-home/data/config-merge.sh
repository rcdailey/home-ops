#!/bin/sh

#==============================================================================
# AdGuard Home GitOps Configuration Merge Script
#==============================================================================
#
# OVERVIEW:
# This script implements an authoritative configuration merge strategy for
# AdGuard Home in a GitOps environment. It allows GitOps to control specific
# configuration fields while preserving user customizations for everything else.
#
# MINIMUM VIABLE CONFIG APPROACH:
# AdGuard Home's validation logic (validateConfig() in config.go) only requires:
# 1. Valid YAML syntax
# 2. Valid HTTP bind addresses (defaults acceptable)
# 3. Valid DNS bind hosts (defaults acceptable)
# 4. No port conflicts (defaults acceptable)
#
# Notably, it does NOT require:
# - Users to be defined
# - DNS servers to be configured
# - Any specific configuration sections
#
# This allows us to use an extremely minimal GitOps template containing only
# the fields we want to control, while letting AdGuard Home use sensible
# defaults for everything else.
#
# ADGUARD HOME SETUP WIZARD BEHAVIOR:
# The setup wizard is triggered by globalContext.firstRun == true, which is
# determined at runtime by whether AdGuard Home can successfully load a valid
# configuration file. If our minimal YAML passes validation, firstRun becomes
# false and the setup wizard is bypassed.
#
# GITOPS AUTHORITATIVE POLICY:
# Fields specified in the GitOps template are considered authoritative and
# will ALWAYS override existing values in the runtime configuration. This
# ensures GitOps maintains control over critical settings like authentication
# credentials while allowing users to customize everything else through the
# AdGuard Home web interface.
#
# MERGE BEHAVIOR:
# 1. If no existing config exists (first run):
#    - Use GitOps template directly
# 2. If existing config exists (upgrade/restart):
#    - Merge existing config with GitOps template
#    - GitOps template values take precedence (authoritative)
#    - User customizations preserved for non-GitOps fields
#    - Comments from GitOps template are stripped (clean runtime config)
#    - User's existing comments are preserved
#
# VARIABLE SUBSTITUTION:
# The GitOps template uses Flux variable substitution with dollar-brace syntax
# which is resolved before this script runs, so the script receives the final values.
#
# SECURITY CONSIDERATIONS:
# - Only authentication-related fields are managed by GitOps
# - Credentials are provided via encrypted Kubernetes secrets
# - No sensitive data is hardcoded in the GitOps template
# - User retains full control over DNS, filtering, and network settings
#
#==============================================================================

set -e  # Exit on any error

EXISTING_CONFIG="/opt/adguardhome/conf/AdGuardHome.yaml"
GITOPS_TEMPLATE="/tmp/AdGuardHome.yaml"
TEMP_MERGED="/opt/adguardhome/conf/merged.yaml"

echo "=== AdGuard Home Configuration Merge ==="

# Check if an existing configuration exists
if [ -f "$EXISTING_CONFIG" ]; then
    echo "✓ Existing configuration found"
    echo "✓ Performing authoritative merge (GitOps values take precedence)"

    # Merge existing config with GitOps template
    # - select(fileIndex == 0): existing config (base)
    # - select(fileIndex == 1): GitOps template (override)
    # - ... comments="": strip comments from GitOps template
    # - * operator: deep merge with right side taking precedence
    yq eval-all 'select(fileIndex == 0) * (select(fileIndex == 1) | ... comments="")' \
        "$EXISTING_CONFIG" \
        "$GITOPS_TEMPLATE" > "$TEMP_MERGED"

    echo "✓ Configuration merged successfully"

else
    echo "✓ No existing configuration found (first run)"
    echo "✓ Using GitOps template directly"

    # First run: use GitOps template as-is (still strip comments for clean runtime)
    yq eval '... comments=""' "$GITOPS_TEMPLATE" > "$TEMP_MERGED"

    echo "✓ Template processed successfully"
fi

# Apply the merged configuration
cp "$TEMP_MERGED" "$EXISTING_CONFIG"
chmod 644 "$EXISTING_CONFIG"

echo "✓ Configuration updated at: $EXISTING_CONFIG"
echo "✓ AdGuard Home will use merged configuration on startup"
echo "=== Configuration merge completed ==="
