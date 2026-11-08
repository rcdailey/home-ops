# Sonarr and Radarr stay on SQLite

- **Status:** Accepted
- **Date:** 2026-11-08
- **Decision:** Keep all Sonarr and Radarr instances on SQLite; if they move to PostgreSQL later,
  give each instance its own 2-instance CNPG cluster

## Context and Problem Statement

Five instances run in the `media` namespace: sonarr, sonarr-anime, radarr, radarr-4k, and
radarr-anime. All use SQLite, which is the default. Sonarr v4 and Radarr v4.1+ also support
PostgreSQL, and some homelab repositories have moved to it. The question is whether to move, and if
so, how to lay out the CNPG clusters.

Measurements on 2026-11-08:

- Logs from the last 30 days have two `database is locked` errors, both from sonarr at 2026-10-24
  06:03. The other four instances have none.
- Main database sizes are 677 MiB (sonarr-anime), 320 MiB (sonarr), 111 MiB (radarr-4k), 88 MiB
  (radarr), and 7 MiB (radarr-anime).
- All five already set `LOG__DBENABLED: "False"`, so the log database is not in use.
- Idle CNPG instances in this cluster use about 55-90 MiB of memory and 10-20m CPU each. The
  barman-cloud backup sidecar adds about 20-50 MiB per instance.

## Considered Options

- **Stay on SQLite** - No change
- **One shared CNPG cluster** - One 2-instance cluster with a database per app
- **One CNPG cluster per app instance** - Five 2-instance clusters, 10 Postgres instances in total

## Decision Outcome

Chosen option: **Stay on SQLite**, because the measured lock contention is negligible and the
databases are small. Postgres would add 10 pods, 10 Ceph volumes, and roughly 0.6-1.4 GiB of memory
without fixing a measured problem.

If a migration becomes necessary, use **one CNPG cluster per app instance**. CNPG recommends one
database per cluster. Backup and point-in-time recovery work on a whole cluster, so a shared cluster
can only roll back all apps together. Separate clusters also allow independent Postgres upgrades and
keep one app's load or outage away from the others. This matches every existing CNPG cluster in this
repository. Create only the main database; the log database stays disabled.

Revisit this decision if `database is locked` errors recur regularly, or if the web UI becomes slow
because of database queries.

## Consequences

- Good, because there are no new clusters, volumes, backups, or Postgres upgrades to maintain
- Good, because the app backup and restore path stays unchanged
- Bad, because slow queries that do not hit a lock timeout are not measured; they would show only as
  a slow web UI
- Bad, because a future migration still needs a one-time data copy (for example with `pgloader`),
  since the apps create an empty schema on Postgres

## References

- [CNPG FAQ: one database per cluster][cnpg-faq]
- [m00nwtchr/homelab-cluster: shared cluster][m00nwtchr]
- [aclerici38/home-ops: shared cluster][aclerici38]
- [joryirving/home-ops: cluster per app][joryirving]
- [x00-sh/home-ops: cluster per app][x00-sh]
- [onedr0p/home-ops: Sonarr on SQLite][onedr0p]

[cnpg-faq]: https://github.com/cloudnative-pg/cloudnative-pg/blob/main/docs/src/faq.md
[m00nwtchr]: https://github.com/m00nwtchr/homelab-cluster/blob/1f64bec4ac581ab50ee5362a633a5dc17bd9145b/kubernetes/apps/postgres/cnpg/cluster/cluster.yaml
[aclerici38]: https://github.com/aclerici38/home-ops/blob/ec20e1973add1556b0802c8c8e2708210d8b27d9/kubernetes/apps/home/cloudnative-pg/cluster/cluster.yaml
[joryirving]: https://github.com/joryirving/home-ops/blob/65fc3db69de6af7bcf25f13efc1ae26854078d21/kubernetes/components/postgres/cluster.yaml
[x00-sh]: https://github.com/x00-sh/home-ops/blob/aa8c523ba0c696665cfa927cbde76a964395a519/kubernetes/apps/media/sonarr/app/postgres.yaml
[onedr0p]: https://github.com/onedr0p/home-ops/blob/8ea3d9ba2341b3b70feb27af3b6205ed199404a3/kubernetes/apps/default/sonarr/app/helmrelease.yaml

## Historical Context

A sample of 16 GitHub homelab repositories in November 2026 found seven active repositories that run
Sonarr or Radarr on Postgres. Five use one shared cluster (m00nwtchr, dsluo, aclerici38, mchestr,
justjon875), and two use a cluster per app (joryirving, x00-sh). The shared-cluster repositories
back up with Barman to S3 and take no per-app dumps. onedr0p, bjw-s-labs, and buroa still use
SQLite. Almost every repository disables the log database. No repository was found that moved from
Postgres back to SQLite. The sample came from web search and well-known repositories, not a full
code search.
