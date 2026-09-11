# CloudNativePG backup component

This component configures one CloudNativePG cluster to archive backups to Garage with the Barman
Cloud plugin. The Garage S3 operator provisions the bucket and its access key.

## Use

The application must contain one `Cluster` named `${APP}-postgres`. Add the component to the
application's `kustomization.yaml`:

```yaml
components:
- ../../../components/cnpg-backup
```

Set `APP` through `postBuild.substitute`, and add dependencies on `cnpg-barman-cloud` in
`kube-system` and `garage-instance` in `storage`.

The component supports one database cluster per application. Add an explicit cluster-name input
before using it with multiple clusters or with a cluster that does not follow the naming convention.

## Resources

For `APP: example`, the component declares:

- `GarageS3AccessKey/example-s3`. The Garage S3 operator creates the `example-s3-gs3ak` Secret.
- `GarageS3Bucket/example-postgres-backups`, backed by the Garage instance in `storage`.
- `ObjectStore/example-postgres-backups`, which tells Barman how to connect to that bucket.
- `ScheduledBackup/example-postgres-backup`, which runs daily at 02:00.

The ObjectStore keeps a 30-day recovery window. The cluster continuously archives WAL and takes
base backups from a standby when one is available.

The component reads the operator-managed `AWS_ACCESS_KEY` and `AWS_SECRET_KEY` fields directly. It
does not create or copy S3 credentials.

## Lifecycle

Bucket and access-key resources disable Flux pruning. Removing the component does not delete backup
data or revoke its key. Retire those resources separately after confirming that their recovery data
is no longer needed.

Provisioning is asynchronous. The Garage operator must create the bucket, Secret, and permissions
before Barman can archive WAL or complete a base backup. Resource creation alone does not prove that
the backup is usable.

Garage data and the Kopia repository share the NAS failure boundary. This component does not create
an offsite copy.
