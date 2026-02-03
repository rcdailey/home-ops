# Donetick Adoption Pending Upstream Fixes

- **Status:** Proposed
- **Date:** 2026-02-03
- **Decision:** Keep donetick deployed but defer family adoption until upstream issues are resolved

## Context and Problem Statement

Donetick is deployed as a task/chore management application. Initial testing revealed two blockers
for family adoption: the inability to enforce OIDC-only authentication (local login remains
available) and missing OIDC support in the Android app for self-hosted instances.

## Considered Options

- **Wait for upstream fixes** - Keep deployed, track issues, adopt when resolved
- **Remove from cluster** - Uninstall until issues are fixed
- **Implement workarounds** - Gateway-level auth blocking, web-only usage

## Decision Outcome

Chosen option: **Wait for upstream fixes**, because the app is functional for single-user testing
and the issues are already tracked upstream with community interest.

## Consequences

- Good, because we maintain familiarity with the app and can adopt quickly when fixed
- Good, because we avoid complex workarounds that may break with updates
- Bad, because the app cannot be used by family members until issues resolve
- Bad, because timeline depends on upstream maintainer priorities

## References

- [Issue #438: Improve user experience when SSO is enabled][issue-438]
- [Issue #268: Android App Bug - Fail to initial SSO for selfhost site][issue-268]

[issue-438]: https://github.com/donetick/donetick/issues/438
[issue-268]: https://github.com/donetick/donetick/issues/268
