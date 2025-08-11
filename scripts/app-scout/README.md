# App Scout - Kubernetes Migration Discovery Tool

App Scout is a command-line interface for [kubesearch.dev](https://kubesearch.dev), designed to
automate the discovery of real-world Kubernetes deployment patterns. This tool enables AI-assisted
analysis and automated searches across thousands of GitOps repositories, making it ideal for
migrating Docker Compose services to Kubernetes and learning deployment best practices from
production environments.

## Quick Start

```bash
# Discover deployment patterns
./scripts/app-scout.sh discover plex

# Find repositories with multiple apps deployed together
./scripts/app-scout.sh correlate blocky external-dns

# Inspect configuration files
./scripts/app-scout.sh inspect plex --repo onedr0p/home-ops --files helmrelease,values
```

## Commands

### Discovery Command

```bash
./scripts/app-scout.sh discover <app_name> [--sample-count N]
```

**Purpose**: Find all deployment patterns for an application
**Output**: JSON showing dedicated charts vs app-template usage with available files

**Example**:

```bash
./scripts/app-scout.sh discover authentik --sample-count 5
```

### Correlate Command

```bash
./scripts/app-scout.sh correlate <app_name1> <app_name2> [...] [--sample-count N]
```

**Purpose**: Find repositories that contain multiple applications deployed together
**Output**: JSON showing repositories with all specified apps and their deployment details

**Example**:

```bash
./scripts/app-scout.sh correlate blocky external-dns --sample-count 10
```

### Inspect Command

```bash
./scripts/app-scout.sh inspect <app_name> --repo <repo_name> --files <file_list>
```

**Purpose**: Get raw file contents from specific repositories
**Output**: Raw file contents with clear separation between files

**File Types**: `helmrelease`, `values`, `configmaps`, `secrets`, `pvcs`, `ingress`, or any filename from discovery
**File Paths**: Use `/path/to/file.yaml` for arbitrary files

**Examples**:

```bash
# Standard file types
./scripts/app-scout.sh inspect plex --repo onedr0p/home-ops --files helmrelease,values

# Specific files found in discovery
./scripts/app-scout.sh inspect cups --repo wipash/homelab --files cupsd.conf

# Arbitrary file paths
./scripts/app-scout.sh inspect app --repo user/repo --files /path/to/config.yaml
```

## Workflow

1. **Discover** → Find deployment patterns and available files
2. **Correlate** → Find architectural patterns where apps are deployed together
3. **Inspect** → Get actual configuration files

## Discovery Output Structure

```json
{
  "app_name": {
    "dedicated_charts": {
      "usage_count": 89,
      "chart_sources": ["k8s-at-home", "truecharts"],
      "repositories": [
        {
          "repo_name": "onedr0p/home-ops",
          "stars": 1500,
          "available_files": {
            "helmrelease": "path/to/helmrelease.yaml",
            "values": "path/to/values.yaml",
            "cupsd.conf": "path/to/resources/cupsd.conf",
            "all_files": ["file1.yaml", "file2.conf", "..."]
          }
        }
      ]
    },
    "app_template": {
      "usage_count": 156,
      "repositories": [...]
    }
  }
}
```

## Key Features

- **Real-world Examples**: Searches 1000+ GitOps repositories
- **Complete File Discovery**: Finds all files in app directories including subdirectories
- **Dual Deployment Patterns**: Shows both dedicated Helm charts and app-template usage
- **Raw File Access**: Returns unmodified file contents
- **No Setup Required**: Proxy script handles dependencies automatically

## File Discovery Scope

Searches these locations around each HelmRelease:

- Same directory as HelmRelease
- Parent directory
- Common subdirectories: `resources/`, `config/`, `configs/`, `files/`

## Use Cases

- **Migration Planning**: See how others deploy the same app
- **Architectural Research**: Discover how applications are combined in production
- **Configuration Examples**: Get proven configurations from active deployments
- **Best Practices**: Learn from most-starred repositories
- **Troubleshooting**: Compare your setup against working examples

## Prerequisites

- GitHub CLI installed and authenticated (`gh auth login`)
- Python 3.6+ (handled by proxy script)
- Internet connection for database download

## Data Source

- **Database**: kubesearch.dev (auto-downloads weekly)
- **File Access**: GitHub API via your authenticated `gh` CLI
- **Updates**: Database refreshes automatically when >7 days old
