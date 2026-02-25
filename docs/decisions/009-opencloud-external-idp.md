# Use External IdP for OpenCloud

- **Status:** Accepted
- **Date:** 2025-11-01
- **Decision:** Use Pocket-ID as external OIDC provider instead of OpenCloud's built-in IdP

## Context and Problem Statement

OpenCloud includes a built-in IdP service, but deploying it behind Envoy Gateway with TLS
termination creates an irreconcilable architecture conflict. The built-in IdP requires HTTPS issuer
URLs, but pods cannot reach themselves through the gateway at the HTTPS port. Internal HTTP URLs are
rejected by IdP validation. Browser CSP blocks localhost URLs from external domains.

## Considered Options

- **Built-in IdP** - Zero additional dependencies, single deployment
- **External IdP (Pocket-ID)** - Separate OIDC provider, already deployed for other apps

## Decision Outcome

Chosen option: **External IdP (Pocket-ID)**, because the built-in IdP has fundamental
incompatibilities with Kubernetes gateway TLS termination patterns. After 10+ failed configuration
attempts, no working configuration was found.

Configuration: `OC_EXCLUDE_RUN_SERVICES: idp` disables the built-in IdP. Pocket-ID provides OIDC at
`https://auth.${SECRET_DOMAIN}`. Role assignment uses a custom `oc_groups` claim via Pocket-ID's
group custom claims feature.

## Consequences

- Good, because eliminates the OIDC circular dependency
- Good, because Pocket-ID already provides SSO for other cluster apps
- Good, because external IdP allows independent scaling and lifecycle
- Bad, because additional dependency on Pocket-ID availability
- Bad, because custom claim mapping (`oc_groups`) required for role assignment

## References

- [OpenCloud built-in IdP investigation][investigation]
- [OpenCloud Authelia groups claim investigation][groups-investigation]

[investigation]: /docs/investigations/opencloud-oidc-configuration-failure-2025-11-01.md
[groups-investigation]: /docs/investigations/opencloud-authelia-groups-claim-2025-11-16.md
