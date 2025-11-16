# OpenCloud Authelia Groups Claim Integration Issue

**Date:** 2025-11-16 **Status:** RESOLVED **Components:** OpenCloud 3.7.0, Authelia 4.39.14

## Problem Statement

OpenCloud integration with Authelia OIDC fails with "no roles in user claims" error, preventing user
login despite successful authentication.

## Symptoms

**Browser error:**

```txt
GET https://opencloud.dailey.app/ocs/v1.php/cloud/capabilities 500 (Internal Server Error)
```

**OpenCloud logs:**

```json
{"level":"error","service":"proxy","error":"no roles in user claims","time":"2025-11-16T15:18:10Z","line":"github.com/opencloud-eu/opencloud/services/proxy/pkg/userroles/oidcroles.go:84","message":"Error mapping role names to role ids"}
```

**User state after login:**

```txt
Not logged in
This could be because of a routine safety log out, or because your account is either inactive or not yet authorized for use.
```

## Root Cause

Authelia requires explicit scope definition to include claims in UserInfo endpoint response. The
`groups` scope was requested by OpenCloud client but not defined in Authelia configuration.

## Architecture Understanding

### OIDC Token Types (Authelia-specific)

1. **ID Token** - JWT containing user identity claims, issued once at login
2. **Access Token** - **Opaque** (random string, not JWT), used for API access
3. **Refresh Token** - Opaque, used to obtain new access tokens

### Why Opaque Access Tokens

**Authelia design choice:** Access tokens are opaque strings stored in Redis, not self-contained
JWTs.

**Benefits:**

- Instant revocation (delete from Redis)
- Claims stay server-side (privacy)
- Smaller token size

**Trade-off:**

- Requires `/userinfo` endpoint call (network overhead)
- Cannot validate locally like JWT signature verification

### OpenCloud Claims Flow

1. User authenticates → Authelia returns authorization code
2. OpenCloud exchanges code for tokens (ID/access/refresh)
3. **OpenCloud calls `/userinfo` with access token** (not ID token)
4. Authelia validates opaque token → returns claims based on **scope definitions**
5. OpenCloud extracts `groups` claim → maps to roles via `proxy.yaml`

**Critical:** OpenCloud reads role claims from `/userinfo` endpoint, NOT from ID token.

## Diagnostic Steps

### 1. Initial Investigation

**Error location:** `services/proxy/pkg/userroles/oidcroles.go:84`

**Finding:** Code shows OpenCloud expects `groups` claim but receives none.

### 2. Configuration Review

**OpenCloud config (helmrelease.yaml):**

- ✅ `PROXY_ROLE_ASSIGNMENT_DRIVER=oidc`
- ❌ Missing `PROXY_ROLE_ASSIGNMENT_OIDC_CLAIM=groups` (initially)
- ✅ Role mapping configured in `proxy.yaml`

**Authelia config (oidc-clients.yaml):**

- ✅ `groups` scope requested in client definition
- ✅ `claims_policy` includes groups in ID token

### 3. Source Code Analysis

**GitHub search:** `opencloud-eu/opencloud`

**Finding:** `services/proxy/pkg/middleware/oidc_auth.go` shows:

- OpenCloud calls `getClaims()` function
- When `PROXY_OIDC_ACCESS_TOKEN_VERIFY_METHOD=none`, calls UserInfo endpoint
- Claims from UserInfo passed to `UpdateUserRoleAssignment()`

**Conclusion:** Groups must be in UserInfo response, not just ID token.

## Attempted Fixes

### Fix #1: Add PROXY_ROLE_ASSIGNMENT_OIDC_CLAIM (Partial)

**Change:** Added `PROXY_ROLE_ASSIGNMENT_OIDC_CLAIM=groups` to OpenCloud config

**Result:** No change, still "no roles in user claims"

**Why it failed:** Environment variable alone doesn't make Authelia return groups claim.

### Fix #2: Remove PROXY_OIDC_ACCESS_TOKEN_VERIFY_METHOD=none (Failed)

**Reasoning:** Maybe skipping token verification also skips UserInfo call

**Change:** Removed `PROXY_OIDC_ACCESS_TOKEN_VERIFY_METHOD=none`

**Result:** 401 Unauthorized errors

**Error:**

```json
{"level":"error","service":"proxy","error":"failed to verify access token: token is malformed: token contains an invalid number of segments"}
```

**Why it failed:** Authelia uses opaque access tokens. OpenCloud tried to parse as JWT → failed.

### Fix #3: Explicit UserInfo Enable (Reverted)

**Change:**

```yaml
PROXY_OIDC_ACCESS_TOKEN_VERIFY_METHOD: none
PROXY_OIDC_SKIP_USER_INFO: "false"
```

**Reasoning:** Explicitly enable UserInfo calls while skipping JWT verification

**Result:** Still "no roles in user claims"

**Why it failed:** UserInfo was already being called. Problem was Authelia response, not OpenCloud
behavior.

### Fix #4: Define groups Scope in Authelia (SOLUTION)

**Root cause identified:** Authelia doesn't automatically return claims for non-standard scopes.

**Change:** Added to `authelia/config/oidc-base.yaml`:

```yaml
scopes:
  groups:
    claims:
      - groups
```

**Why this works:** Tells Authelia "when client requests `groups` scope, include `groups` claim in
UserInfo response."

**Status:** Pending validation (changes committed but not yet tested)

## Key Learnings

### OIDC Scopes vs Claims

**Standard scopes** (built-in):

- `openid` - Required for OIDC
- `profile` - name, preferred_username, etc.
- `email` - email, email_verified
- `address` - Physical mailing address
- `phone` - Phone number

**Custom scopes** (must be defined):

- `groups` - Not standard, requires explicit definition
- Any app-specific scopes

**In Authelia:** Must map scope → claims via `scopes:` configuration section.

### OpenCloud Token Verification Modes

**PROXY_OIDC_ACCESS_TOKEN_VERIFY_METHOD values:**

1. **`jwt`** - Parse access token as JWT, verify signature with JWKS
   - Requires: JWT-formatted access tokens
   - Validates: Token signature, expiry, issuer
   - Performance: No network call needed

2. **`none`** - Skip JWT validation, use token for UserInfo only
   - Requires: `PROXY_OIDC_SKIP_USER_INFO=false` (enforced)
   - Validates: Token validity via UserInfo endpoint
   - Performance: Network call to `/userinfo` per request

**For Authelia:** Must use `none` (opaque tokens aren't JWTs)

### claims_policy vs scopes

**claims_policy:** Controls what goes in **ID token**

```yaml
claims_policies:
  opencloud:
    id_token:
      - groups  # Groups in ID token
```

**scopes:** Controls what goes in **UserInfo response**

```yaml
scopes:
  groups:
    claims:
      - groups  # Groups in UserInfo
```

**Both required for OpenCloud:** ID token for initial login, UserInfo for role mapping.

## Final Configuration

### Authelia (oidc-base.yaml)

```yaml
identity_providers:
  oidc:
    scopes:
      groups:
        claims:
          - groups
    claims_policies:
      opencloud:
        id_token:
          - groups
          - preferred_username
          - email
```

### OpenCloud (helmrelease.yaml)

```yaml
env:
  PROXY_ROLE_ASSIGNMENT_DRIVER: oidc
  PROXY_ROLE_ASSIGNMENT_OIDC_CLAIM: groups
  PROXY_OIDC_ACCESS_TOKEN_VERIFY_METHOD: none
  PROXY_OIDC_SKIP_USER_INFO: "false"
```

### OpenCloud (config/proxy.yaml)

```yaml
role_assignment:
  driver: oidc
  oidc_role_mapper:
    role_claim: groups
    role_mapping:
      - role_name: admin
        claim_value: admins
      - role_name: user
        claim_value: users
```

## References

**Discord advice (m00n):**

- Correctly identified Authelia misconfiguration
- Suggested creating custom `roles` claim as workaround
- Actual fix simpler: just define `groups` scope

**OpenCloud source code:**

- `services/proxy/pkg/userroles/oidcroles.go:84` - Error source
- `services/proxy/pkg/middleware/oidc_auth.go` - UserInfo call location
- `services/proxy/pkg/config/config.go` - Environment variable definitions

**Authelia documentation:**

- Custom scopes require explicit definition
- Standard scopes (openid/profile/email) built-in only

## Actual Root Cause (Trace Logs - 2025-11-16)

**Finding:** OpenCloud authorization request only includes scopes `[openid profile email]` -
**missing `groups` scope**.

**Evidence from Authelia trace logs:**

```txt
Authorization Request with id '477ba236...' scope="[openid profile email]"
```

**Confirmed:**

- User HAS groups in Authelia: `[admins]`
- Authelia client config ALLOWS `groups` scope
- OpenCloud application NOT REQUESTING `groups` scope

**Conclusion:** Need to configure OpenCloud to request `groups` scope in authorization requests.

### Fix #5: Configure OpenCloud to Request groups Scope (ACTUAL SOLUTION)

**Root cause:** OpenCloud defaults to requesting only `openid profile email` scopes. Must explicitly
request `groups` scope.

**Change:** Added to `opencloud/helmrelease.yaml`:

```yaml
WEB_OIDC_SCOPE: "openid profile email groups"
```

**Why this works:** The `WEB_OIDC_SCOPE` environment variable controls which OIDC scopes the web
service requests during authentication.

**Reference:** ownCloud Infinite Scale Web Service documentation

**Status:** ✅ VALIDATED - Web client login successful with role assignment

## Known Limitations

**Native apps (Desktop/Android/iOS):** May have hardcoded scopes without `groups`. If native apps
fail role assignment, alternative solutions:

1. Use custom `roles` claim instead of `groups` (configure in both Authelia and OpenCloud)
2. Wait for OpenCloud to make native app scopes configurable
3. Test desktop client to confirm issue exists

## Cleanup Tasks

After successful validation:

1. Revert Authelia log level: `trace` → `info`
2. Revert OpenCloud log level: `debug` → `info`
3. Archive this troubleshooting doc for future reference

## Prevention

**When integrating OIDC apps with Authelia:**

1. Check if app needs custom claims (groups, roles, etc.)
2. Define scope in Authelia `scopes:` section
3. Add scope to client `scopes:` list
4. Add claim to `claims_policies` if app uses ID token
5. Test with actual login, check UserInfo response

**When seeing "no X in claims" errors:**

1. Verify claim in users.yaml
2. Check scope definition in oidc-base.yaml
3. Verify client requests scope
4. Check if app reads from ID token vs UserInfo
5. Test UserInfo endpoint directly if possible
