# CloudNativePG recovery

Use this runbook to restore a CloudNativePG physical backup created by the Barman Cloud plugin. A
restore must create an isolated cluster. It must not reuse production Services or PVCs.

## Preconditions

- The Barman plugin and Garage instance are ready.
- The source bucket and its operator-managed credential Secret still exist.
- The source archive identity is known. This repository uses `${APP}-postgres`.
- The intended recovery time is known, or the latest recoverable state is acceptable.
- The restored cluster has a new name and new PVCs.

## Prepare the restore

Add a temporary, Git-managed recovery overlay. Reference the existing source ObjectStore through an
external cluster. Set `serverName` in the plugin parameters, not on the ObjectStore:

```yaml
spec:
  bootstrap:
    recovery:
      source: source
  externalClusters:
  - name: source
    plugin:
      name: barman-cloud.cloudnative-pg.io
      parameters:
        barmanObjectName: example-postgres-backups
        serverName: example-postgres
```

For point-in-time recovery, add the required recovery target under
`bootstrap.recovery.recoveryTarget` using the CloudNativePG recovery API. Keep the target earlier
than the latest archived WAL.

Do not configure the restored cluster to archive new WAL into the source archive. If the recovery
test requires ongoing archiving, provision a separate ObjectStore and bucket for the restored
cluster.

## Recover and validate

1. Commit and reconcile the isolated recovery overlay through Flux.
2. Confirm that the new cluster becomes healthy and that all requested instances are ready.
3. Connect only to the restored cluster and verify representative application records.
4. For a point-in-time test, verify records on both sides of the selected recovery time.
5. Record whether the test covered a pre-migration archive, a plugin-created backup, and WAL replay.

Use `./scripts/hops.sh db status` and `./scripts/hops.sh app events <namespace>` for cluster status
and events. If `hops` lacks evidence required during recovery, follow its documented escape hatch
instead of querying the cluster with raw tools.

## Cleanup

Remove the recovery overlay through Git only after validation is complete. Confirm that its PVCs and
any test-only bucket contain no required data before authorizing deletion. Never delete the source
bucket, source credentials, production cluster, production PVCs, or production archive as cleanup.
