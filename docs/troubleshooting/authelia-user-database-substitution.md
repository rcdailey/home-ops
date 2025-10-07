# Authelia User Database Variable Substitution - Complete Investigation

**Date:** 2025-10-08 **Status:** RESOLVED - Using Flux postBuild.substituteFrom **Issue:** Authelia
crashed with "configuration key not expected" errors when trying to use template syntax in user
database file

## Executive Summary

Initial Authelia deployment crashed because the user database file (`users.yaml`) used Go template
syntax (`{{ env "VAR" }}`) to inject secrets. Authelia validates the user database YAML schema
**before** processing template filters, causing validation failures. Resolved by switching to Flux's
`postBuild.substituteFrom` mechanism which substitutes variables (`${VAR}`) before the ConfigMap is
created, ensuring Authelia receives valid YAML with literal string values.

## Current Solution (Flux postBuild.substituteFrom)

**Configuration:**

```yaml
# kubernetes/apps/default/authelia/config/users.yaml
users:
  robert:
    disabled: false
    displayname: Robert Dailey
    password: ${ROBERT_PASSWORD_HASH}
    email: ${ROBERT_EMAIL}
    groups:
    - admins
```

```yaml
# kubernetes/apps/default/authelia/ks.yaml
spec:
  postBuild:
    substituteFrom:
    - kind: Secret
      name: cluster-secrets
    - kind: Secret
      name: authelia-secret
```

**How it works:**

1. ExternalSecret creates `authelia-secret` with keys: `ROBERT_PASSWORD_HASH`, `ROBERT_EMAIL`
2. Flux's `postBuild.substituteFrom` reads variables from `authelia-secret`
3. Flux runs variable substitution (`${VAR}` → actual values) BEFORE ConfigMap generation
4. Kustomize's `configMapGenerator` creates ConfigMap with final values
5. Authelia reads ConfigMap containing valid YAML with literal strings

**Benefits:**

- Variables substituted at build time (outside Authelia)
- Authelia receives valid YAML that passes schema validation
- No special template filters or processing needed in Authelia
- Clean separation: Flux handles substitution, Authelia handles authentication

## The Problem

### Initial Configuration (FAILED)

```yaml
# users.yaml (WRONG - violates schema)
users:
  robert:
    password: {{ env "ROBERT_PASSWORD_HASH" }}
    email: {{ env "ROBERT_EMAIL" }}
```

```yaml
# helmrelease.yaml (WRONG - template filter doesn't help)
env:
  X_AUTHELIA_CONFIG_FILTERS: template
command:
- authelia
- --config=/etc/authelia/configuration.yaml
- --config=/etc/authelia/users.yaml  # Loading user DB as config file!
```

### Error Messages

```txt
time="2025-10-08T03:42:54-04:00" level=error msg="Configuration: configuration key not expected: users.robert.disabled"
time="2025-10-08T03:42:54-04:00" level=error msg="Configuration: configuration key not expected: users.robert.displayname"
time="2025-10-08T03:42:54-04:00" level=error msg="Configuration: configuration key not expected: users.robert.email"
time="2025-10-08T03:42:54-04:00" level=error msg="Configuration: configuration key not expected: users.robert.groups"
time="2025-10-08T03:42:54-04:00" level=error msg="Configuration: configuration key not expected: users.robert.password"
time="2025-10-08T03:42:54-04:00" level=fatal msg="Can't continue due to the errors loading the configuration"
```

### Root Cause Analysis

**Why template filters don't work:**

1. Authelia validates YAML against JSON schema:
   `https://www.authelia.com/schemas/v4.39/json-schema/user-database.json`
2. Schema validation happens **BEFORE** template filter processing
3. Template syntax (`{{ env "VAR" }}`) violates schema (expects literal string for `password` field)
4. Authelia crashes during validation, never reaching template processing stage

**Template Filter Scope:**

- `X_AUTHELIA_CONFIG_FILTERS=template` enables Go template processing for **configuration files**
- User database files have strict schema requirements
- Schema validation is non-negotiable security feature
- Templates can only be used in main `configuration.yaml`, not user database files

## Investigation Timeline

### Attempt 1: Go Template Syntax with Template Filter

**Configuration:**

```yaml
# users.yaml
password: {{ env "ROBERT_PASSWORD_HASH" }}
email: {{ env "ROBERT_EMAIL" }}

# helmrelease.yaml
env:
  X_AUTHELIA_CONFIG_FILTERS: template
envFrom:
- secretRef:
    name: authelia-secret  # Contains ROBERT_PASSWORD_HASH, ROBERT_EMAIL
```

**Result:** FAILED - Schema validation before template processing

**Error:** "configuration key not expected: users.robert.password"

### Attempt 2: Fix Path Configuration

**Discovery:** `authentication_backend.file.path` pointed to `/config/users.yaml` but file mounted
at `/etc/authelia/users.yaml`

**Fix:** Updated configuration.yaml:

```yaml
authentication_backend:
  file:
    path: /etc/authelia/users.yaml  # Changed from /config/users.yaml
```

**Result:** FAILED - Still crashed with same schema errors

**Learning:** Path was wrong, but didn't address core schema validation issue

### Attempt 3: Remove User Database from --config

**Discovery:** Loading `users.yaml` via `--config` argument treats it as a configuration file, not a
user database

**Previous command:**

```bash
authelia --config=/etc/authelia/configuration.yaml --config=/etc/authelia/users.yaml
```

**Fixed command:**

```bash
authelia --config=/etc/authelia/configuration.yaml
# User database loaded via authentication_backend.file.path setting
```

**Result:** FAILED - Still crashed because ConfigMap still contained template syntax

**Learning:** User database must be loaded via `authentication_backend.file.path`, not `--config`
argument

### Attempt 4: Flux postBuild.substituteFrom (SUCCESS)

**Configuration:**

```yaml
# users.yaml - Use Flux variable syntax
password: ${ROBERT_PASSWORD_HASH}
email: ${ROBERT_EMAIL}

# ks.yaml - Add substituteFrom
postBuild:
  substituteFrom:
  - kind: Secret
    name: authelia-secret
```

**Result:** SUCCESS - Pod running, authentication working

**Key insight:** Flux substitutes variables BEFORE ConfigMap creation, so Authelia receives valid
YAML

## Technical Understanding

### Authelia Configuration Loading Order

1. **Parse command-line arguments** (`--config` paths)
2. **Load and merge configuration files** (main config + any additional configs)
3. **Validate configuration schema** (JSON schema validation)
4. **Apply template filters** (if `X_AUTHELIA_CONFIG_FILTERS` set)
5. **Load user database** (from `authentication_backend.file.path`)
6. **Validate user database schema** (JSON schema validation)
7. **Start server**

**Critical point:** Schema validation happens BEFORE template processing for both configuration and
user database files.

### Variable Substitution Approaches

#### 1. Authelia Template Filter (X_AUTHELIA_CONFIG_FILTERS)

- **Scope:** Configuration files only (main `configuration.yaml`)
- **Syntax:** Go templates (`{{ env "VAR" }}`, `{{ secret "/path" }}`)
- **Timing:** After schema validation (TOO LATE for user database)
- **Use case:** Dynamic configuration values (domains, URLs, etc.)

#### 2. Flux postBuild.substituteFrom

- **Scope:** ALL Kubernetes manifests (including ConfigMaps)
- **Syntax:** Shell-style variables (`${VAR}`)
- **Timing:** Before resource creation (BEFORE Authelia sees it)
- **Use case:** Injecting secrets into any YAML file

#### 3. ExternalSecret Template Engine

- **Scope:** Secret data fields
- **Syntax:** Go templates (`{{ .key }}`)
- **Timing:** During Secret creation
- **Use case:** Generating complex secret content (not needed here)

### Why postBuild.substituteFrom is Correct

**Execution Flow:**

```txt
Git Repo → Flux → postBuild.substituteFrom → Kustomize → ConfigMap → Authelia
          ↓
    Read authelia-secret
          ↓
    ${VAR} → actual values
```

**At each stage:**

1. **Git:** Files contain `${VAR}` placeholders
2. **Flux:** Reads `authelia-secret`, replaces `${VAR}` with actual values
3. **Kustomize:** Generates ConfigMap with substituted values
4. **Authelia:** Reads ConfigMap containing literal strings (valid YAML)

**Why this works:**

- Substitution happens OUTSIDE Authelia (in GitOps pipeline)
- ConfigMap contains final values, not template syntax
- Authelia's schema validation sees valid YAML
- No special processing needed in Authelia

## Current Implementation

### File: kubernetes/apps/default/authelia/config/users.yaml

```yaml
# yaml-language-server: $schema=https://www.authelia.com/schemas/v4.39/json-schema/user-database.json
---
# Authelia user database
# Password hash and email substituted by Flux from authelia-secret via postBuild.substituteFrom

users:
  robert:
    disabled: false
    displayname: Robert Dailey
    password: ${ROBERT_PASSWORD_HASH}
    email: ${ROBERT_EMAIL}
    groups:
    - admins
```

### File: kubernetes/apps/default/authelia/ks.yaml

```yaml
spec:
  postBuild:
    substituteFrom:
    - kind: Secret
      name: cluster-secrets
    # REQUIRED: users.yaml contains ${ROBERT_PASSWORD_HASH} and ${ROBERT_EMAIL} that must be
    # substituted by Flux BEFORE the ConfigMap is created. Authelia's X_AUTHELIA_CONFIG_FILTERS
    # template filter cannot be used because Authelia validates the user database YAML schema
    # before processing templates, and {{ env "VAR" }} syntax violates the schema (password must
    # be a literal string). postBuild.substituteFrom runs before ConfigMap generation, ensuring
    # Authelia receives valid YAML with actual values instead of variable references.
    - kind: Secret
      name: authelia-secret
```

### File: kubernetes/apps/default/authelia/externalsecret.yaml

```yaml
spec:
  target:
    name: authelia-secret
    template:
      engineVersion: v2
      data:
        AUTHELIA_SESSION_SECRET: "{{ .session_secret }}"
        AUTHELIA_STORAGE_ENCRYPTION_KEY: "{{ .storage_encryption_key }}"
        AUTHELIA_IDENTITY_VALIDATION_RESET_PASSWORD_JWT_SECRET: "{{ .jwt_secret }}"
        ROBERT_PASSWORD_HASH: "{{ .robert_password_hash }}"
        ROBERT_EMAIL: "{{ .robert_email }}"
  data:
  - secretKey: robert_password_hash
    remoteRef:
      key: /default/authelia/robert-password-hash
  - secretKey: robert_email
    remoteRef:
      key: /default/authelia/robert-email
```

### File: kubernetes/apps/default/authelia/config/configuration.yaml

```yaml
authentication_backend:
  file:
    path: /etc/authelia/users.yaml  # Must match ConfigMap mount path
```

### File: kubernetes/apps/default/authelia/helmrelease.yaml

```yaml
controllers:
  authelia:
    annotations:
      reloader.stakater.com/auto: "true"
    strategy: Recreate
    containers:
      main:
        env:
          TZ: America/New_York
          # No X_AUTHELIA_CONFIG_FILTERS needed
        envFrom:
        - secretRef:
            name: authelia-secret
        command:
        - authelia
        - --config=/etc/authelia/configuration.yaml
        # Users loaded via authentication_backend.file.path, not --config

persistence:
  config-files:
    type: configMap
    name: authelia-config
    advancedMounts:
      authelia:
        main:
        - path: /etc/authelia/configuration.yaml
          subPath: configuration.yaml
          readOnly: true
        - path: /etc/authelia/users.yaml
          subPath: users.yaml
          readOnly: true
```

## Alternative Approaches Considered

### 1. Write User Database to Persistent Volume

**Concept:** Use init container to write `users.yaml` to `/config/` PVC with template expansion

**Pros:**

- Keeps user database separate from ConfigMap
- Could use environment variables for substitution

**Cons:**

- Adds complexity (init container, volume coordination)
- User database changes require pod restart
- Not GitOps-friendly (state in volume, not Git)
- Reloader can't detect changes

**Verdict:** REJECTED - Unnecessary complexity

### 2. Separate Secret for User Database

**Concept:** Create dedicated Secret for entire `users.yaml` content using ExternalSecret template

**Configuration:**

```yaml
# users-secret.yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
spec:
  target:
    name: authelia-users
    template:
      data:
        users.yaml: |
          users:
            robert:
              password: {{ .robert_password_hash }}
              email: {{ .robert_email }}
```

**Pros:**

- User database in Secret (appropriate for sensitive data)
- ExternalSecret handles templating

**Cons:**

- Embedded YAML in template (hard to maintain)
- Can't use yaml-language-server schema validation
- Duplicates structure from source files

**Verdict:** REJECTED - Poor maintainability compared to postBuild.substituteFrom

### 3. LDAP Backend

**Concept:** Switch from file-based to LDAP authentication backend

**Pros:**

- Centralized user management
- No need to embed passwords in YAML
- Better for multi-user environments

**Cons:**

- Requires LDAP server deployment
- Massive scope increase for single-user homelab
- Overkill for current requirements

**Verdict:** OUT OF SCOPE - File backend appropriate for homelab scale

## Validation Commands

```bash
# Check pod status
kubectl get pods -n default -l app.kubernetes.io/name=authelia

# View recent events
kubectl get events -n default --sort-by='.lastTimestamp' | rg authelia | tail -30

# Check pod logs
kubectl logs -n default -l app.kubernetes.io/name=authelia --tail=50

# Verify ConfigMap contains substituted values (not variables)
kubectl get configmap authelia-config -n default -o yaml | rg -A5 "users.yaml"

# Verify Secret contains variables for substitution
kubectl get secret authelia-secret -n default -o jsonpath='{.data}' | jq

# Test authentication
curl -I https://auth.${SECRET_DOMAIN}/api/health
```

## Files Modified

- `kubernetes/apps/default/authelia/config/users.yaml` - Changed from `{{ env "VAR" }}` to `${VAR}`
- `kubernetes/apps/default/authelia/ks.yaml` - Added `authelia-secret` to `postBuild.substituteFrom`
- `kubernetes/apps/default/authelia/config/configuration.yaml` - Updated
  `authentication_backend.file.path`
- `kubernetes/apps/default/authelia/helmrelease.yaml` - Removed `X_AUTHELIA_CONFIG_FILTERS`, removed
  `--config=/etc/authelia/users.yaml`, added reloader annotation
- `docs/troubleshooting/authelia-user-database-substitution.md` - This document

## Key Learnings

1. **Schema validation order matters** - Authelia validates YAML structure before processing
   templates
2. **Template filters have scope limits** - `X_AUTHELIA_CONFIG_FILTERS` works for configuration, not
   user database
3. **Flux substitution timing is critical** - `postBuild.substituteFrom` runs before resource
   creation
4. **User database loading method** - Must use `authentication_backend.file.path`, not `--config`
   argument
5. **Path consistency is important** - `authentication_backend.file.path` must match actual mount
   location

## References

- Authelia Configuration Methods: <https://www.authelia.com/configuration/methods/files/>
- Authelia User Database Schema:
  <https://www.authelia.com/schemas/v4.39/json-schema/user-database.json>
- Flux Kustomization postBuild:
  <https://fluxcd.io/flux/components/kustomize/kustomizations/#post-build-variable-substitution>
- Authelia File Backend: <https://www.authelia.com/configuration/first-factor/file/>
