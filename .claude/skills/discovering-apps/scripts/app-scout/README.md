# App Scout - Kubernetes Migration Discovery Tool

App Scout is a command-line interface for [kubesearch.dev](https://kubesearch.dev), designed to automate the discovery of real-world Kubernetes deployment patterns. This tool enables AI-assisted analysis and automated searches across thousands of GitOps repositories, making it ideal for migrating Docker Compose services to Kubernetes and learning deployment best practices from production environments.

## Quick Start

```bash
# Discover deployment patterns
scripts/app-scout.sh discover plex

# Find repositories with multiple apps deployed together
scripts/app-scout.sh correlate blocky external-dns
```

## Commands

### Discovery Command

```bash
scripts/app-scout.sh discover <app_name> [--sample-count N]
```

**Purpose**: Find all deployment patterns for an application
**Output**: JSON showing dedicated charts vs app-template usage

**Example**:

```bash
scripts/app-scout.sh discover sonarr --sample-count 5
```

### Correlate Command

```bash
scripts/app-scout.sh correlate <app_name1> <app_name2> [...] [--sample-count N]
```

**Purpose**: Find repositories that contain multiple applications deployed together
**Output**: JSON showing repositories with all specified apps and their deployment details

**Example**:

```bash
scripts/app-scout.sh correlate blocky external-dns --sample-count 10
```

## Workflow

1. **Discover** → Find deployment patterns and repository information
2. **Correlate** → Find architectural patterns where apps are deployed together
3. **Inspect Files** → Use octocode MCP tools for file retrieval

## File Inspection with OctoCode MCP

After discovering repositories, use octocode MCP tools to inspect configuration files:

**Available Tools**:
- `githubViewRepoStructure`: Explore repository directory structure
- `githubSearchCode`: Search for specific code patterns across files
- `githubGetFileContent`: Retrieve complete file contents

**Example Workflow**:

```bash
# Step 1: Discover repositories using app-scout
scripts/app-scout.sh discover plex

# Step 2: Use octocode MCP tools to inspect files (via Claude)
# - githubViewRepoStructure for onedr0p/home-ops kubernetes/apps
# - githubSearchCode for "plex" in helmrelease files
# - githubGetFileContent to read specific helmrelease.yaml files
```

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
          "release_name": "plex",
          "chart_name": "plex",
          "chart_version": "1.2.3",
          "namespace": "media",
          "url": "https://github.com/onedr0p/home-ops/blob/main/.../helmrelease.yaml",
          "helm_repo_name": "k8s-at-home",
          "description": "My home operations repository",
          "last_commit": "2025-01-15T10:30:00Z"
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
- **Dual Deployment Patterns**: Shows both dedicated Helm charts and app-template usage
- **Repository Metadata**: Includes stars, descriptions, last commit dates
- **No Setup Required**: Proxy script handles dependencies automatically
- **OctoCode Integration**: Seamless transition to file inspection via MCP tools

## Use Cases

- **Migration Planning**: See how others deploy the same app
- **Architectural Research**: Discover how applications are combined in production
- **Configuration Examples**: Identify repositories with working configurations
- **Best Practices**: Learn from most-starred repositories
- **Troubleshooting**: Compare your setup against working examples

## Prerequisites

- GitHub CLI installed and authenticated (`gh auth login`)
- Python 3.6+ (handled by proxy script)
- Internet connection for database download

## Data Source

- **Database**: kubesearch.dev (auto-downloads weekly)
- **Repository Access**: GitHub API via your authenticated `gh` CLI
- **Updates**: Database refreshes automatically when >7 days old
