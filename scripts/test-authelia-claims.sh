#!/usr/bin/env bash
# Test Authelia OIDC claims hydration for OpenCloud client
# This script uses Authelia's built-in debug command to verify groups claim behavior

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Authelia OIDC Claims Test for OpenCloud${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Test configuration
NAMESPACE="default"
DEPLOYMENT="authelia"
USERNAME="robert"
CLIENT_ID="web"
SCOPES="openid profile email groups"

echo -e "${YELLOW}Test Configuration:${NC}"
echo "  Namespace:  ${NAMESPACE}"
echo "  Deployment: ${DEPLOYMENT}"
echo "  Username:   ${USERNAME}"
echo "  Client ID:  ${CLIENT_ID}"
echo "  Scopes:     ${SCOPES}"
echo ""

echo -e "${YELLOW}Running Authelia OIDC claims debug...${NC}"
echo ""

# Run the debug command with proper config paths and claims policy
kubectl exec -n "${NAMESPACE}" "deploy/${DEPLOYMENT}" -- \
    authelia debug oidc claims "${USERNAME}" \
    --config /etc/authelia/configuration.yaml \
    --config /etc/authelia/oidc-base.yaml \
    --config /etc/authelia/oidc-clients.yaml \
    --client-id "${CLIENT_ID}" \
    --policy "opencloud" \
    --scopes "${SCOPES}" \
    --grant-type "authorization_code" \
    --response-type "code" \
    2>&1 | tee /tmp/authelia-claims-test.log

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${YELLOW}Analysis of Results:${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Parse the output for specific information
if grep -q "groups" /tmp/authelia-claims-test.log; then
    echo -e "${GREEN}✓ 'groups' claim found in output${NC}"
    echo ""
    echo -e "${YELLOW}Groups claim details:${NC}"
    grep -A2 "groups" /tmp/authelia-claims-test.log || true
else
    echo -e "${RED}✗ 'groups' claim NOT found in output${NC}"
    echo ""
    echo -e "${YELLOW}This indicates Authelia may not be including groups in claims.${NC}"
fi

echo ""
echo -e "${YELLOW}Key Points to Verify:${NC}"
echo "1. Check if 'groups' appears in the ID Token claims"
echo "2. Check if 'groups' appears in the UserInfo claims"
echo "3. Verify the groups value matches: ['admins']"
echo ""

echo -e "${YELLOW}Full output saved to: /tmp/authelia-claims-test.log${NC}"
