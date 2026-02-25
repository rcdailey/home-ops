# Use Shared Kopia Repository for VolSync Backups

- **Status:** Accepted
- **Date:** 2025-10-04
- **Decision:** All apps share a single Kopia repository with snapshot-level isolation instead of
  per-app repository isolation

## Context and Problem Statement

VolSync Kopia backups need a repository strategy. Per-app S3 prefix isolation failed due to a
trailing slash stripping bug in VolSync's entry.sh script (commit `09ef3a7` reversed the correct
behavior). The VolSync Kopia maintainer recommended shared repository as the intended pattern.

## Considered Options

- **Shared repository** - All apps write to one repository, isolated by Kopia username/hostname
  snapshots
- **Per-app S3 prefix** - Each app gets its own repository under a prefix (`s3://bucket/appname/`)
- **Per-app S3 bucket** - Each app gets its own bucket (`s3://volsync-appname/`)

## Decision Outcome

Chosen option: **Shared repository**, because it enables cross-app deduplication and is the
maintainer-recommended pattern. Kopia's multi-tenancy support via username/hostname provides
snapshot-level isolation within a single repository.

All apps use the same repository password (required; repository-level authentication). VolSync
automatically sets `KOPIA_OVERRIDE_USERNAME` to the app name and `KOPIA_OVERRIDE_HOSTNAME` to the
namespace, producing snapshots like `prowlarr@media:/data`.

The backend later migrated from Garage S3 to NFS filesystem (commit `cd396e0`) but the shared
repository pattern remains unchanged.

## Consequences

- Good, because content deduplication works across all apps
- Good, because single repository simplifies management and monitoring
- Good, because works reliably with current VolSync implementation
- Bad, because all apps must share the same repository password
- Bad, because per-app retention policies not possible at repository level

## References

- [VolSync Kopia shared repository investigation][investigation]
- [Backup strategy architecture][backup-strategy]
- [VolSync Kopia PR #1723][volsync-pr]

[investigation]: /docs/investigations/volsync-kopia-shared-repository.md
[backup-strategy]: /docs/architecture/backup-strategy.md
[volsync-pr]: https://github.com/backube/volsync/pull/1723
