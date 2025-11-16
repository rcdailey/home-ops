#!/usr/bin/env bash
# Test script to verify Authelia's UserInfo endpoint returns groups claim
# when the groups scope is requested in the access token

set -euo pipefail

# Configuration
AUTHELIA_URL="${AUTHELIA_URL:-https://auth.dailey.lol}"
CLIENT_ID="${CLIENT_ID:-web}"
SCOPE="${SCOPE:-openid profile email groups}"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Authelia UserInfo Endpoint Test${NC}"
echo "=================================="
echo ""
echo "This script will help you test the Authelia UserInfo endpoint."
echo "You need to provide an access token that was issued with the 'groups' scope."
echo ""
echo -e "${YELLOW}Instructions:${NC}"
echo "1. Open your browser to: ${AUTHELIA_URL}"
echo "2. Log in if not already authenticated"
echo "3. Use browser dev tools (Network tab) to capture an OAuth flow"
echo "4. Extract the access_token from the token response"
echo ""
echo -e "${YELLOW}Alternative - Use Authelia CLI:${NC}"
echo "If you have access to the Authelia pod, you can use:"
echo "  kubectl exec -n default deploy/authelia-app -- \\"
echo "    authelia debug oidc claims robert --client-id web --scopes groups openid profile email"
echo ""
read -p "Enter your access token (or press Ctrl+C to exit): " ACCESS_TOKEN

if [[ -z "$ACCESS_TOKEN" ]]; then
    echo -e "${RED}Error: Access token is required${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}Testing UserInfo endpoint...${NC}"
echo "URL: ${AUTHELIA_URL}/api/oidc/userinfo"
echo ""

# Call the UserInfo endpoint
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    "${AUTHELIA_URL}/api/oidc/userinfo")

# Split response into body and status code
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

echo -e "${YELLOW}HTTP Status Code:${NC} ${HTTP_CODE}"
echo ""
echo -e "${YELLOW}Response Body:${NC}"
echo "$BODY" | jq -C . 2>/dev/null || echo "$BODY"
echo ""

# Check for groups claim
if echo "$BODY" | jq -e '.groups' >/dev/null 2>&1; then
    GROUPS=$(echo "$BODY" | jq -r '.groups | join(", ")')
    echo -e "${GREEN}✓ Success: 'groups' claim found in UserInfo response${NC}"
    echo -e "  Groups: ${GROUPS}"
else
    echo -e "${RED}✗ Error: 'groups' claim NOT found in UserInfo response${NC}"
    echo ""
    echo -e "${YELLOW}Available claims:${NC}"
    echo "$BODY" | jq -r 'keys | join(", ")' 2>/dev/null || echo "Unable to parse claims"
fi

echo ""
echo -e "${YELLOW}Full claim details:${NC}"
echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
