# App Scout

App Scout queries the [kubesearch.dev] database for Kubernetes deployment examples. It reports
dedicated Helm charts and app-template releases without requiring GitHub authentication.

## Quick Start

```bash
./scripts/app-scout.sh discover plex

./scripts/app-scout.sh correlate blocky external-dns
```

## Commands

### Discover

```bash
./scripts/app-scout.sh discover <app-name> [--sample-count N]
```

The result separates dedicated charts from app-template deployments. Each section reports the
number of matching deployments, the number of repositories, and a sample of repositories.

### Correlate

```bash
./scripts/app-scout.sh correlate <app-name> <app-name> [...] [--sample-count N]
```

Correlation uses the same matching rules as discovery and returns repositories containing every
requested application. Duplicate application names are rejected.

## Output

```json
{
  "database": {
    "release": "2026-08-17",
    "published_at": "2026-08-17T01:31:33Z",
    "source": "https://github.com/whazor/k8s-at-home-search/releases/download/2026-08-17/repos.db",
    "cached_at": "2026-08-17T02:00:00+00:00",
    "stale": false,
    "latest_record_at": "2026-08-17T00:49:02+00:00"
  },
  "plex": {
    "dedicated_charts": {
      "deployment_count": 89,
      "repository_count": 64,
      "chart_sources": ["example"],
      "repositories": [
        {
          "repo_name": "owner/repository",
          "stars": 100,
          "source_ref": "main",
          "release_name": "plex",
          "chart_name": "plex",
          "chart_version": "1.2.3",
          "namespace": "media",
          "manifest_url": "https://github.com/owner/repository/blob/main/app/helmrelease.yaml",
          "manifest_path": "app/helmrelease.yaml",
          "helm_repo_name": "example"
        }
      ]
    }
  }
}
```

`chart_version` is the Helm chart version. `source_ref` is the repository branch used by
`manifest_url`; do not use the chart version as a Git ref.

App-template names match when the requested name is bounded by non-alphanumeric characters. For
example, `sonarr` matches `sonarr-exporter` but `arr` does not match `sonarr`.

## Prerequisites

- Python 3.11 or later
- Internet connection for database download

## Data Source

App Scout caches `repos.db` in `${XDG_CACHE_HOME:-~/.cache}/app-scout`. It checks the downloaded
database before replacing the cache. If a refresh fails, App Scout warns and continues with an
existing valid database.

[kubesearch.dev]: https://kubesearch.dev
