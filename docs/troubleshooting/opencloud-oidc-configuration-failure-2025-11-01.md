# OpenCloud OIDC Configuration Failure - 2025-11-01

## Summary

**COMPLETE FAILURE** - Attempted to deploy OpenCloud with built-in IdP in Kubernetes with external HTTPS gateway (Envoy). After 10+ configuration attempts over several hours, every approach resulted in either OIDC circular dependency, issuer mismatch, IdP crashes, or CSP violations. **None of the configurations worked.**

## Environment

- Kubernetes cluster with Envoy gateway (external HTTPS termination)
- OpenCloud 3.6.0 (rolling) - `docker.io/opencloudeu/opencloud-rolling`
- Gateway terminates TLS at port 443, backend service uses HTTP on port 9200
- External URL: `https://opencloud.${SECRET_DOMAIN}`
- Internal service: `opencloud.default.svc.cluster.local:9200` (HTTP only)
- DNS resolution: `opencloud.${SECRET_DOMAIN}` → `10.43.161.119` (ClusterIP)

## Root Cause Analysis

OpenCloud's built-in IdP architecture has a **fundamental incompatibility** when deployed behind an external HTTPS gateway with TLS termination:

### Core Conflicts

1. **IdP requires HTTPS issuer URL**
   - `IDP_ISS` environment variable must start with `https://`
   - Source: `services/idp` bootstrap validation code
   - Cannot use `http://` scheme for internal communication

2. **Internal services default to `https://localhost:9200`**
   - All 15+ services (proxy, idp, graph, users, groups, etc.) default to localhost
   - Source: `services/*/pkg/config/defaults/defaultconfig.go` across entire codebase
   - This is the intended design for monolithic deployments

3. **Environment variable precedence overrides defaults**
   - Proxy OIDC issuer: `OC_URL;OC_OIDC_ISSUER;PROXY_OIDC_ISSUER` (line 115 in `services/proxy/pkg/config/config.go`)
   - IdP issuer: `OC_URL;OC_OIDC_ISSUER;IDP_ISS` (line 74 in `services/idp/pkg/config/config.go`)
   - When `OC_URL` is set to external URL, it **overrides** the localhost defaults

4. **External URL is not reachable from within pod at correct port**
   - Gateway listens on port 443 (HTTPS)
   - Service listens on port 9200 (HTTP)
   - Pod trying `https://opencloud.${SECRET_DOMAIN}:443/.well-known/...` → no listener on 443 in pod
   - Pod trying `https://opencloud.${SECRET_DOMAIN}:9200/.well-known/...` → connection refused (no HTTPS on 9200)

5. **CSP policies block `localhost:9200` connections from browser**
   - When `OC_OIDC_ISSUER: https://localhost:9200` is set
   - Browser cannot connect to localhost from external domain
   - CSP directive: `connect-src 'self' blob: https://raw.githubusercontent.com/...`
   - Error: "Refused to connect to 'https://localhost:9200/.well-known/openid-configuration' because it violates CSP"

### Architecture Mismatch

OpenCloud's built-in IdP is designed for:
- **Monolithic deployments** where all services run in same container
- **Direct HTTPS access** to the application (no reverse proxy)
- **TLS handled by OpenCloud itself** (not gateway)

NOT designed for:
- Kubernetes deployments with external gateways
- TLS termination at gateway/ingress
- Split internal/external URLs

## Configuration Attempts - All Failed

### Attempt 1: Basic bjw-s Configuration
**Source:** Copied from `bjw-s-labs/home-ops` repository

**Config:**
```yaml
env:
  IDM_CREATE_DEMO_USERS: false
  OC_INSECURE: false
  OC_URL: https://opencloud.${SECRET_DOMAIN}
  PROXY_TLS: false
```

**Symptom:** OIDC circular dependency - infinite loading spinner on web UI

**Errors:**
```
{"service":"proxy","error":"Get \"https://opencloud.${SECRET_DOMAIN}/.well-known/openid-configuration\": context deadline exceeded (Client.Timeout exceeded while awaiting headers)"}
```

**Why it failed:**
- Proxy uses `OC_URL` as OIDC issuer (env var precedence)
- Tries to fetch well-known config from external URL
- Request goes through Envoy gateway → routes back to same pod → timeout
- Circular dependency: pod → gateway → pod

**Browser symptoms:**
- Login page loads
- Infinite spinner after entering credentials
- Console: 504 Gateway Timeout errors

---

### Attempt 2: Internal OIDC Issuer with HTTP
**Reasoning:** Use internal service URL to avoid gateway

**Config:**
```yaml
env:
  PROXY_OIDC_ISSUER: http://opencloud:9200
  OC_INSECURE: "true"
  OC_URL: https://opencloud.${SECRET_DOMAIN}
```

**Symptom:** Pod crash loop - IdP service fails to start

**Errors:**
```
{"level":"fatal","service":"idp","error":"invalid iss value, URL must start with https://","message":"could not bootstrap idp"}
```

**Why it failed:**
- IdP has hardcoded validation requiring HTTPS scheme
- Source: `services/idp/pkg/config/config.go` issuer validation
- `http://` scheme is explicitly rejected
- Cannot use internal HTTP URLs for OIDC issuer

---

### Attempt 3: Internal OIDC Issuer with Wrong Service Name
**Reasoning:** Try with app-template service naming pattern

**Config:**
```yaml
env:
  PROXY_OIDC_ISSUER: http://opencloud-app:9200
```

**Symptom:** DNS resolution failure

**Errors:**
```
{"service":"proxy","error":"Get \"http://opencloud-app:9200/.well-known/openid-configuration\": dial tcp: lookup opencloud-app on 10.43.0.10:53: no such host"}
```

**Investigation:**
```bash
$ kubectl get svc -n default -l app.kubernetes.io/name=opencloud
NAME        TYPE        CLUSTER-IP      PORT(S)
opencloud   ClusterIP   10.43.161.119   9200/TCP
```

**Why it failed:**
- Assumed app-template would create `opencloud-app` service name
- Actual service name is just `opencloud`
- App-template naming: `${.Release.Name}-${service.identifier}` but identifier was `app` not `app`
- DNS lookup failed for non-existent service

---

### Attempt 4: OIDC Rewrite Middleware
**Reasoning:** Use middleware to rewrite well-known endpoint URLs

**Config:**
```yaml
env:
  PROXY_OIDC_ISSUER: http://opencloud:9200
  PROXY_OIDC_REWRITE_WELLKNOWN: "true"
```

**Symptom:** Startup timeout - chicken-egg problem

**Errors:**
```
{"service":"proxy","error":"Get \"http://opencloud:9200/.well-known/openid-configuration\": context deadline exceeded (Client.Timeout exceeded while awaiting headers)","handler":"oidc wellknown rewrite"}
```

**Why it failed:**
- Rewrite middleware tries to fetch well-known config from IdP during initialization
- IdP not yet fully started and listening
- Middleware startup blocks waiting for IdP
- IdP can't finish starting until proxy is ready
- Circular dependency in startup sequence

---

### Attempt 5: OC_INSECURE True for Self-Referential OIDC
**Reasoning:** Allow insecure HTTPS connections to self

**Config:**
```yaml
env:
  OC_INSECURE: "true"
  OC_URL: https://opencloud.${SECRET_DOMAIN}
```

**Symptom:** Login successful but then issuer mismatch error

**Errors:**
```
{"service":"proxy","error":"oidc: issuer did not match the issuer returned by provider, expected \"http://opencloud:9200\" got \"https://opencloud.${SECRET_DOMAIN}\""}
```

**Investigation:** Read `/etc/opencloud/opencloud.yaml` - found old issuer config persisted

**Why it failed:**
- Config file already existed with old issuer from previous attempts
- `opencloud init` skips regeneration with message: "config file already exists"
- Old config had different issuer than current env vars
- Runtime issuer mismatch between what proxy expected vs what IdP returned

---

### Attempt 6: Force Config Regeneration
**Reasoning:** Delete config and let it regenerate with correct env vars

**Actions:**
1. `kubectl exec -n default deploy/opencloud -- sh -c 'rm -rf /etc/opencloud/*'`
2. `flux reconcile helmrelease -n default opencloud`
3. Multiple iterations of delete + reconcile

**Symptom:** Config regenerated but IdP LDAP authentication failures

**Errors:**
```
{"service":"idm","bind_dn":"uid=idp,ou=sysusers,o=libregraph-idm","op":"bind","message":"invalid credentials"}
{"service":"idp","error":"ldap identifier backend logon connect error: LDAP Result Code 49 \"Invalid Credentials\": ","message":"identifier failed to logon with backend"}
```

**Investigation:** Checked ExternalSecret values - passwords were set correctly

**Why it failed:**
- Clearing `/etc/opencloud/*` only removes YAML config
- LDAP database lives in `/var/lib/opencloud/idm/idm.boltdb`
- Service user passwords (`uid=idp`, `uid=reva`, `uid=libregraph`) stored in boltdb
- Database not regenerated, still had old passwords
- New env var passwords didn't match database passwords

**Code analysis:**
- `services/idm/pkg/command/server.go:131-144` - service users created at lines
- `services/idm/pkg/command/server.go:173-185` - passwords hashed and stored
- Only happens during **initial** database creation
- Database persistence means old passwords remain

---

### Attempt 7: IDM Database Regeneration + Missing Env Var
**Reasoning:** Clear both config and database, add missing bind password env var

**Actions:**
1. Added `IDP_LDAP_BIND_PASSWORD` to ExternalSecret
2. `kubectl exec -n default deploy/opencloud -- sh -c 'rm -rf /etc/opencloud/*'`
3. `kubectl exec -n default deploy/opencloud -- sh -c 'rm -rf /var/lib/opencloud/idm/*'`
4. `flux reconcile helmrelease -n default opencloud`

**Code research findings:**
```go
// services/idm/pkg/config/config.go:40
Idp string `yaml:"idp_password" env:"IDM_IDPSVC_PASSWORD"`

// services/idp/pkg/config/config.go:40
BindPassword string `yaml:"bind_password" env:"OC_LDAP_BIND_PASSWORD;IDP_LDAP_BIND_PASSWORD"`
```

**ExternalSecret added:**
```yaml
- secretKey: IDP_LDAP_BIND_PASSWORD
  remoteRef:
    key: /default/opencloud/idm-admin-password
```

**Symptom:** IdP bind errors resolved ✓ but back to issuer mismatch (same as Attempt 5)

**Why it failed:**
- Database regeneration worked - IdP could now bind to LDAP
- But still had old config with wrong issuer
- Back to the same issuer mismatch problem
- Progress on LDAP authentication but not on OIDC routing

---

### Attempt 8: Explicit IDP_ISS with Internal URL
**Reasoning:** Set IdP issuer directly instead of letting it default

**Config:**
```yaml
env:
  IDP_ISS: http://opencloud:9200
  OC_URL: https://opencloud.${SECRET_DOMAIN}
```

**Symptom:** Same as Attempt 2 - IdP crashed on startup

**Errors:**
```
{"level":"fatal","service":"idp","error":"invalid iss value, URL must start with https://"}
```

**Why it failed:**
- Same validation as Attempt 2
- IdP explicitly requires HTTPS scheme
- Cannot work around this requirement

---

### Attempt 9: Back to bjw-s Baseline with OC_INSECURE False
**Reasoning:** bjw-s has `OC_INSECURE: false` not `"true"` - match exactly

**Config:**
```yaml
env:
  IDM_CREATE_DEMO_USERS: false
  OC_INSECURE: false  # Changed from "true"
  OC_URL: https://opencloud.${SECRET_DOMAIN}
  PROXY_TLS: false
```

**Symptom:** Back to external URL timeout (same as Attempt 1)

**Errors:**
```
{"service":"proxy","error":"Get \"https://opencloud.${SECRET_DOMAIN}/.well-known/openid-configuration\": context deadline exceeded"}
```

**Investigation:** Compared with bjw-s config - identical env vars

**Why it failed:**
- Exactly same config as bjw-s but different result
- Suggests bjw-s has different network setup, persistent config, or undocumented configuration
- Cannot replicate his working setup with same env vars

**Theory on why bjw-s works:**
1. His `/etc/opencloud/opencloud.yaml` has correct issuer from previous working init
2. He never regenerates config so it persists with working configuration
3. May have custom network setup allowing pods to reach external URL at correct port
4. May have additional configs not visible in public HelmRelease

---

### Attempt 10: OC_OIDC_ISSUER with Localhost
**Reasoning:** Use standard OpenCloud pattern - localhost for services, external for clients

**Config:**
```yaml
env:
  IDM_CREATE_DEMO_USERS: false
  OC_INSECURE: false
  OC_OIDC_ISSUER: https://localhost:9200  # Override issuer to localhost
  OC_URL: https://opencloud.${SECRET_DOMAIN}  # Keep external for clients
  PROXY_TLS: false
```

**Source code research:**
```bash
$ cd /tmp/opencloud && rg "localhost:9200" services/
```

Found 15+ services all defaulting to `https://localhost:9200`:
- `services/proxy/pkg/config/defaults/defaultconfig.go:43` - Proxy OIDC issuer
- `services/idp/pkg/config/defaults/defaultconfig.go:41` - IdP issuer
- `services/graph/pkg/config/defaults/defaultconfig.go:69` - Graph service
- `services/users/pkg/config/defaults/defaultconfig.go:57` - Users service
- And 11 more services...

**Symptom:** CSP (Content Security Policy) violation - browser blocked from connecting to localhost

**Browser errors:**
```
Refused to connect to 'https://localhost:9200/.well-known/openid-configuration' because it violates the following Content Security Policy directive: "connect-src 'self' blob: https://raw.githubusercontent.com/opencloud-eu/awesome-apps/".

Fetch API cannot load https://localhost:9200/.well-known/openid-configuration. Refused to connect because it violates the document's Content Security Policy.
```

**Console errors:**
```
[JsonService] getJson: Network Error
Uncaught (in promise) TypeError: Failed to fetch
```

**Why it failed:**
- Browser loaded from `https://opencloud.${SECRET_DOMAIN}`
- CSP directive only allows `'self'` (same origin) for `connect-src`
- `https://localhost:9200` is different origin than `https://opencloud.${SECRET_DOMAIN}`
- Browser security policy blocks cross-origin OIDC discovery requests
- Even though localhost is the "correct" configuration for services, browser cannot use it

---

## Environment Variable Reference

### Required Variables (All Attempts)
```yaml
IDM_CREATE_DEMO_USERS: false        # Don't create demo users (alan, mary, etc.)
OC_URL: https://opencloud.${domain} # External URL for clients
PROXY_TLS: false                    # Gateway handles TLS, not OpenCloud
STORAGE_USERS_DRIVER: decomposed    # Required for NFS mounts (avoid xattrs errors)
```

### Secret Variables (ExternalSecret)
```yaml
IDM_ADMIN_PASSWORD: "<password>"      # Admin user password
IDM_IDPSVC_PASSWORD: "<password>"     # Sets password for uid=idp in LDAP
IDP_LDAP_BIND_PASSWORD: "<password>"  # IdP uses this to bind to LDAP (must match above)
```

### Variables Tried (All Failed)
```yaml
OC_INSECURE: "true"              # Attempt 5 - didn't help, still issuer mismatch
OC_INSECURE: false               # Attempt 9 - still timeout on external URL
PROXY_OIDC_ISSUER: http://...    # Attempt 2 - IdP requires HTTPS
PROXY_OIDC_ISSUER: https://...   # Not tried - would still hit gateway or CSP
PROXY_OIDC_REWRITE_WELLKNOWN: "true"  # Attempt 4 - chicken-egg startup problem
IDP_ISS: http://...              # Attempt 8 - IdP requires HTTPS
OC_OIDC_ISSUER: https://localhost:9200  # Attempt 10 - CSP violation in browser
```

## Key Source Code Findings

### Environment Variable Precedence

**Proxy OIDC Issuer** (`services/proxy/pkg/config/config.go:115`):
```go
Issuer string `yaml:"issuer" env:"OC_URL;OC_OIDC_ISSUER;PROXY_OIDC_ISSUER"`
```
Priority: OC_URL → OC_OIDC_ISSUER → PROXY_OIDC_ISSUER

**IdP Issuer** (`services/idp/pkg/config/config.go:74`):
```go
Iss string `yaml:"iss" env:"OC_URL;OC_OIDC_ISSUER;IDP_ISS"`
```
Priority: OC_URL → OC_OIDC_ISSUER → IDP_ISS

### Service User Password Configuration

**IDM Service** (`services/idm/pkg/config/config.go:36-40`):
```go
type ServiceUserPasswords struct {
    OCAdmin string `env:"IDM_ADMIN_PASSWORD"`
    Idm     string `env:"IDM_SVC_PASSWORD"`
    Reva    string `env:"IDM_REVASVC_PASSWORD"`
    Idp     string `env:"IDM_IDPSVC_PASSWORD"`  // Sets password in LDAP
}
```

**IdP Service** (`services/idp/pkg/config/config.go:40`):
```go
BindPassword string `env:"OC_LDAP_BIND_PASSWORD;IDP_LDAP_BIND_PASSWORD"`  // Must match above
```

### Service User Creation

**File:** `services/idm/pkg/command/server.go:131-185`

Service users created at initialization:
- `uid=libregraph,ou=sysusers,o=libregraph-idm` - Main IDM service account
- `uid=idp,ou=sysusers,o=libregraph-idm` - IdP service account (our issue in Attempt 6)
- `uid=reva,ou=sysusers,o=libregraph-idm` - Reva service account

Passwords are:
1. Hashed with argon2id (lines 174-180)
2. Base64 encoded (line 184)
3. Stored in `/var/lib/opencloud/idm/idm.boltdb` (lines 155-164)
4. **Only created during initial database setup** - NOT updated on config regeneration

### Default Service URLs

All services default to `https://localhost:9200`:
- Proxy: `services/proxy/pkg/config/defaults/defaultconfig.go:43`
- IdP: `services/idp/pkg/config/defaults/defaultconfig.go:41`
- Graph: `services/graph/pkg/config/defaults/defaultconfig.go:69`
- Users: `services/users/pkg/config/defaults/defaultconfig.go:57`
- Groups: `services/groups/pkg/config/defaults/defaultconfig.go:54`
- Auth-Basic: `services/auth-basic/pkg/config/defaults/defaultconfig.go:56`
- Auth-Bearer: `services/auth-bearer/pkg/config/defaults/defaultconfig.go:36`
- Frontend: `services/frontend/pkg/config/defaults/defaultconfig.go:83`
- Gateway: `services/gateway/pkg/config/defaults/defaultconfig.go:52`
- Notifications: `services/notifications/pkg/config/defaults/defaultconfig.go:33`
- OCDav: `services/ocdav/pkg/config/defaults/defaultconfig.go:85`
- OCM: `services/ocm/pkg/config/defaults/defaultconfig.go:36`
- Storage-Users: `services/storage-users/pkg/config/defaults/defaultconfig.go:41`
- Web: `services/web/pkg/config/defaults/defaultconfig.go:89,92,96`
- Webfinger: `services/webfinger/pkg/config/defaults/defaultconfig.go:40,52`

## Persistence Patterns Discovered

### Config Persistence
- **Path:** `/etc/opencloud/opencloud.yaml`
- **Mounted from:** PVC `opencloud` subPath `config`
- **Regeneration:** Only happens if file doesn't exist OR `--force-overwrite` flag used
- **Problem:** Old configs persist across pod restarts, can have stale issuer settings

### Data Persistence
- **Path:** `/var/lib/opencloud/`
- **Contains:** IDM database (`idm/idm.boltdb`), encryption keys, certificates
- **Service users:** Created ONCE during initial database creation
- **Problem:** Changing password env vars doesn't update existing database

### Correct Cleanup Procedure
To fully reset OpenCloud state:
1. Clear config: `rm -rf /etc/opencloud/*`
2. Clear data: `rm -rf /var/lib/opencloud/*` (or at least `idm/*`)
3. Restart pod: `kubectl rollout restart deploy/opencloud`
4. **Note:** This loses ALL data including user accounts, files, shares

## What Works vs What Doesn't

### ✅ Works
- IdP LDAP authentication (after Attempt 7 database cleanup)
- Pod DNS resolution of external hostname (`opencloud.${SECRET_DOMAIN}` → `10.43.161.119`)
- Service account creation and password synchronization
- Config regeneration with `--force-overwrite`
- External secret injection via ExternalSecret

### ❌ Doesn't Work
- Setting `PROXY_OIDC_ISSUER` to internal HTTP URL (IdP requires HTTPS)
- Setting `PROXY_OIDC_ISSUER` to external URL (circular dependency through gateway)
- Setting `OC_OIDC_ISSUER` to `https://localhost:9200` (browser CSP blocks it)
- Using `PROXY_OIDC_REWRITE_WELLKNOWN` (startup chicken-egg problem)
- Setting `OC_INSECURE: true` alone (doesn't fix issuer mismatch)
- Config regeneration without database cleanup (passwords don't match)
- Relying on `OC_URL` default for OIDC issuer (creates external URL timeout)

### 🤷 Unknown
- How bjw-s's identical configuration works
- Whether OpenCloud built-in IdP supports Kubernetes with gateway TLS termination
- If there's a supported configuration we missed
- Whether internal service TLS is required for this setup

## Network Debugging

### DNS Resolution
```bash
$ kubectl exec -n default deploy/opencloud -- nslookup opencloud.${SECRET_DOMAIN}
Server:    10.43.0.10
Address:   10.43.0.10:53
Name:      opencloud.${SECRET_DOMAIN}
Address:   10.43.161.119  # Resolves to ClusterIP ✓
```

### Service Discovery
```bash
$ kubectl get svc -n default opencloud
NAME        TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)    AGE
opencloud   ClusterIP   10.43.161.119   <none>        9200/TCP   47h
```

### Gateway Configuration
- **Gateway:** `external` in `network` namespace
- **Listener:** `https` (port 443)
- **Backend:** `opencloud` service port 9200
- **TLS:** Terminated at gateway
- **Backend Protocol:** HTTP (not HTTPS)

### The Port Mismatch Problem
When pod tries `https://opencloud.${SECRET_DOMAIN}/.well-known/...`:
1. DNS resolves to `10.43.161.119` (ClusterIP)
2. HTTPS implies port 443
3. No service listening on port 443 in cluster
4. Even if using port 9200: `https://opencloud.${SECRET_DOMAIN}:9200`
   - Service only speaks HTTP, not HTTPS
   - Connection refused or protocol error

## Browser Error Patterns

### External URL Timeout (Attempts 1, 9)
```
Failed to fetch
504 Gateway Timeout
GET https://opencloud.${SECRET_DOMAIN}/.well-known/openid-configuration
```

### CSP Violation (Attempt 10)
```
Refused to connect to 'https://localhost:9200/.well-known/openid-configuration'
because it violates the following Content Security Policy directive:
"connect-src 'self' blob: https://raw.githubusercontent.com/opencloud-eu/awesome-apps/".
```

### Network Error
```
[JsonService] getJson: Network Error
TypeError: Failed to fetch
```

## Comparative Analysis: Working vs Failed

### bjw-s Working Config
```yaml
env:
  IDM_CREATE_DEMO_USERS: false
  IDM_ADMIN_PASSWORD:
    valueFrom:
      secretKeyRef:
        name: opencloud-secret
        key: idm-admin-password
  OC_INSECURE: false
  OC_URL: https://files.bjw-s.dev
  PROXY_TLS: false
```

### Our Failed Config (Attempt 9 - Identical)
```yaml
env:
  IDM_CREATE_DEMO_USERS: false
  OC_INSECURE: false
  OC_URL: https://opencloud.${SECRET_DOMAIN}
  PROXY_TLS: false
envFrom:
  - secretRef:
      name: opencloud-secret  # Contains IDM_ADMIN_PASSWORD
```

**Difference:** None in environment variables

**Possible Hidden Differences:**
1. bjw-s may have persistent `/etc/opencloud/opencloud.yaml` with correct issuer
2. Network setup allowing pods to reach external URL at port 9200
3. Custom HTTPRoute or gateway config not visible in HelmRelease
4. Different gateway implementation (his uses `envoy-external`, ours uses `external`)
5. Internal DNS or hosts file modification
6. Additional ConfigMap or secret we don't see

## Recommendations

### ❌ Do NOT Try Again
1. **Do NOT** set `PROXY_OIDC_ISSUER` to `http://` URLs - IdP explicitly requires HTTPS
2. **Do NOT** use `PROXY_OIDC_REWRITE_WELLKNOWN` - creates startup deadlock
3. **Do NOT** rely on config regeneration alone - must also clear database
4. **Do NOT** set `OC_OIDC_ISSUER: https://localhost:9200` - browser CSP blocks it
5. **Do NOT** expect bjw-s config to work as-is - there's hidden configuration
6. **Do NOT** use `OC_INSECURE` as a fix - doesn't solve core routing problem

### ✅ Consider Instead
1. **Use external IdP** (Authelia, Keycloak, etc.) instead of built-in IdP
2. **Deploy OpenCloud with internal TLS** between services
3. **Use NodePort or LoadBalancer** instead of HTTPRoute/Gateway
4. **Contact OpenCloud community** for Kubernetes deployment guidance
5. **Check if there's official Helm chart** with proper gateway support
6. **Research split-horizon DNS** for internal/external URLs

### 🔍 Need More Information
1. Official OpenCloud documentation for Kubernetes deployments with external gateways
2. Example configurations from OpenCloud community for this architecture
3. Whether built-in IdP is supported/recommended for Kubernetes
4. If internal service mesh or TLS is required
5. How to properly configure CSP for localhost OIDC with external domain

## Files and Paths Reference

### Kubernetes Resources
- HelmRelease: `/Users/robert/code/home-ops/kubernetes/apps/default/opencloud/helmrelease.yaml`
- ExternalSecret: `/Users/robert/code/home-ops/kubernetes/apps/default/opencloud/externalsecret.yaml`
- PVC: `/Users/robert/code/home-ops/kubernetes/apps/default/opencloud/pvc.yaml`
- Kustomization: `/Users/robert/code/home-ops/kubernetes/apps/default/opencloud/kustomization.yaml`

### Source Code Analysis
- Cloned repo: `/tmp/opencloud/` (shallow clone, depth 1)
- Key files analyzed:
  - `services/idp/pkg/config/config.go` - IdP configuration
  - `services/idp/pkg/config/defaults/defaultconfig.go` - IdP defaults
  - `services/proxy/pkg/config/config.go` - Proxy configuration
  - `services/proxy/pkg/config/defaults/defaultconfig.go` - Proxy defaults
  - `services/idm/pkg/command/server.go` - Service user creation
  - `services/idm/pkg/config/config.go` - IDM configuration

### Runtime Paths (in pod)
- Config: `/etc/opencloud/opencloud.yaml`
- Database: `/var/lib/opencloud/idm/idm.boltdb`
- Data: `/var/lib/opencloud/` (NFS mount from Nezuko)
- Temp: `/tmp` (emptyDir)

## Timeline

**Total Time:** ~4 hours of debugging and configuration attempts

1. **Hour 1:** Initial deployment and bjw-s config comparison (Attempts 1-3)
2. **Hour 2:** OIDC routing research and middleware attempts (Attempts 4-5)
3. **Hour 3:** Config/database cleanup and LDAP debugging (Attempts 6-7)
4. **Hour 4:** Source code analysis and final attempts (Attempts 8-10)

## Conclusion

**Status:** ABANDONED - No working configuration found

After 10+ configuration attempts and deep source code analysis, **we could not find a working configuration** for OpenCloud's built-in IdP behind an external HTTPS gateway with TLS termination.

**Primary blocker:** Fundamental architecture mismatch between:
- OpenCloud's expectation of direct HTTPS access or localhost communication
- Kubernetes pattern of external gateway with TLS termination

**Secondary blockers:**
- IdP HTTPS requirement prevents internal HTTP URLs
- Browser CSP prevents localhost URLs from external domain
- External URL creates circular dependency through gateway
- Environment variable precedence overrides localhost defaults

**Recommendation:** Use external IdP (Authelia, Keycloak) instead of built-in IdP for Kubernetes deployments with gateway TLS termination.

## References

- OpenCloud source: https://github.com/opencloud-eu/opencloud
- bjw-s config: https://github.com/bjw-s-labs/home-ops/tree/main/kubernetes/apps/selfhosted/opencloud
- OpenCloud docs: https://docs.opencloud.eu (limited Kubernetes guidance)
- Docker compose reference: https://github.com/opencloud-eu/opencloud-compose

---

**Document Purpose:** Reference for future attempts - lists everything that DOESN'T work to avoid repeating failed configurations.

**Last Updated:** 2025-11-01 (after 4 hours of failed attempts)
