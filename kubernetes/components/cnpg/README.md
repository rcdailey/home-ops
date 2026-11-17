# CloudNativePG baseline component

Every application with a CloudNativePG `Cluster` includes this component. It merges shared
PostgreSQL parameters into each `Cluster` in the application and keeps the cluster's own parameters.

```yaml
components:
- ../../../components/cnpg
```

| Parameter         | Value     | Reason                                                                           |
| ----------------- | --------- | -------------------------------------------------------------------------------- |
| `wal_level`       | `replica` | CNPG defaults to `logical`, which adds WAL that no cluster consumes.             |
| `wal_compression` | `lz4`     | Compresses full-page images in WAL, reducing disk, standby, and archive traffic. |

The component's values override the same parameters in a cluster's manifest. Before adding logical
replication to a cluster, remove this component from its application.

Changing either parameter makes CNPG restart the cluster: standbys first, then a switchover.
