# OpenCloud Authelia Groups Claim Integration Issue

**Date:** 2025-11-16 **Status:** PARTIALLY RESOLVED **Components:** OpenCloud 3.7.0, Authelia 4.39.14

**Resolution:**
- ✅ Web client: Fixed via `WEB_OIDC_SCOPE: "openid profile email groups"`
- ⚠️ Native apps (Desktop/Android/iOS): UNRESOLVED - hardcoded scopes, no `groups` scope requested

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

## Known Limitations - CONFIRMED ISSUE (2025-11-16 Evening Session)

**Native apps (Desktop/Android/iOS) DO have hardcoded scopes without `groups`.**

### Evidence from Authelia Logs (Android Client)

**Authorization request:**

```txt
Authorization Request with id 'f63f63e5-7055-42e2-a507-6d22e9a0807b' on client with id
'OpenCloudAndroid' using policy 'one_factor' scope="[openid offline_access email profile]"
```

**UserInfo response:**

```txt
User Info Response with id '5188494e-e79c-44a3-b193-bfe709b1f0be' on client with id
'OpenCloudAndroid' is being sent with the following claims:
map[email:authelia@rdailey.me email_verified:true name:Robert Dailey preferred_username:robert
rat:1763335498 sub:28025fe3-56e4-4322-9327-7c081554cdf1 updated_at:1763335575]
```

**Critical findings:**

- Android client requests: `[openid offline_access email profile]`
- NO `groups` scope requested
- UserInfo response contains NO `groups` or `opencloud_groups` claim
- User HAS `groups: [admins]` in Authelia configuration

**Conclusion:** Native apps cannot request custom scopes, confirming issue #217 root cause.

## Additional Fix Attempts (2025-11-16 Evening)

### Fix #6: Attempt to Redefine Standard `profile` Scope (FAILED - CRITICAL ERROR)

**Reasoning:** MASTERBLASTER (Discord) mentioned "custom claims get returned with the profile
scope" in PocketID. Attempted to add `opencloud_groups` to `profile` scope since native apps
request it.

**Change attempted:**

```yaml
scopes:
  profile:
    claims:
      - name
      - preferred_username
      - email
      - opencloud_groups
```

**Result:** Authelia crashed with configuration error:

```txt
time="2025-11-16T18:01:20-05:00" level=error msg="Configuration: identity_providers: oidc:
scopes: scope with name 'profile' can't be used as a custom scope because it's a standard scope"
```

**Why it failed:** Standard OIDC scopes (`profile`, `email`, `openid`, `address`, `phone`) are
protected and cannot be redefined in the `scopes:` section. The `scopes:` section is ONLY for
custom scopes.

**Key learning:** Cannot add custom claims to standard scopes via `scopes:` configuration.

### Fix #7: Use Custom Claims in claims_policy (ATTEMPTED - INEFFECTIVE)

**Reasoning:** Authelia documentation shows `claims_policies` can include `custom_claims` that map
user attributes to claim names. These should be returned regardless of scope requested.

**Change:** Added to `oidc-base.yaml`:

```yaml
claims_policies:
  opencloud:
    custom_claims:
      opencloud_groups:
        attribute: 'groups'
    id_token:
      - opencloud_groups
      - preferred_username
      - email
    access_token:
      - opencloud_groups
      - preferred_username
      - email
```

**Expected behavior:** `opencloud_groups` claim should appear in UserInfo response even when client
doesn't request `groups` scope.

**Actual behavior:** UserInfo response still contains NO `opencloud_groups` claim (see Android logs
above).

**Status:** INEFFECTIVE - custom claims in `claims_policies` do not automatically appear in UserInfo
endpoint.

**Hypothesis:** Claims may only be delivered via UserInfo when associated with a requested scope, OR
there's a separate `userinfo:` section needed in `claims_policies`.

## Potential Solution: GitHub Discussion #1640 Approach

**Source:** <https://github.com/orgs/opencloud-eu/discussions/1640>

**User report:** Successfully configured OpenCloud + Authelia + LLDAP using a different approach
than standard `groups` claim.

### Authelia Configuration (Discussion #1640)

**Step 1: Define user attribute with CEL expression**

```yaml
definitions:
  user_attributes:
    opencloud_admin:
      expression: '"admin-group" in groups ? "opencloudAdmin" : "opencloudUser"'
```

**Step 2: Map attribute to custom claim**

```yaml
identity_providers:
  oidc:
    claims_policies:
      opencloud:
        custom_claims:
          roles:
            attribute: 'opencloud_admin'
        id_token:
          - roles
```

**Step 3: Add to client scopes**

```yaml
clients:
  - client_id: web
    scopes:
      - openid
      - profile
      - email
      - roles  # Custom scope for roles claim
```

### OpenCloud Configuration (Discussion #1640)

```yaml
PROXY_ROLE_ASSIGNMENT_DRIVER: "default"  # NOT "oidc"
PROXY_ROLE_ASSIGNMENT_OIDC_CLAIM: "roles"  # NOT "groups"
PROXY_AUTOPROVISION_ACCOUNTS: "true"
```

**Key differences from standard approach:**

1. Uses `definitions.user_attributes` for CEL expression evaluation
2. Custom `roles` claim instead of `groups`
3. `PROXY_ROLE_ASSIGNMENT_DRIVER: "default"` instead of `"oidc"`
4. Client requests custom `roles` scope

**Potential adaptation for native apps:**

If Authelia's `claims_policies.custom_claims` can be delivered via standard `profile` scope (needs
verification), this approach might work without requiring native apps to request custom scopes.

**Next steps to verify:**

1. Research if custom claims in `claims_policies` appear in UserInfo for standard scopes
2. Test if `definitions.user_attributes` approach delivers claims differently
3. Verify if there's a `userinfo:` section in `claims_policies` configuration
4. Consider asking Authelia community/maintainers about UserInfo claim delivery mechanism

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
