# App Scout

**Kubernetes Application Discovery Tool for Migration Planning**

App Scout helps you migrate Docker Compose services to Kubernetes by discovering real-world
deployment patterns from thousands of GitOps repositories. It searches the
[kubesearch.dev](https://kubesearch.dev) database to find how others deploy the same applications
you're trying to migrate.

## What It Does

**Two-phase workflow:**
1. **Discover** - Find all deployment patterns for an app (dedicated Helm charts vs app-template
   usage)
2. **Inspect** - Fetch actual configuration files from specific repositories

**Key Features:**
- Searches 1000+ real GitOps repositories automatically
- Finds both dedicated Helm charts AND app-template configurations
- Returns exact file paths and repository metadata
- No API tokens needed (uses your `gh auth` setup)
- JSON output perfect for AI analysis

## Quick Start

**Prerequisites:**
- GitHub CLI installed and authenticated (`gh auth login`)
- Python 3.6+

**Basic Usage:**
```bash
# Discover deployment patterns for Plex
task scripts:app-scout:discover -- plex

# Get actual configuration files from a specific repo
task scripts:app-scout:inspect -- plex --repo angelnu/k8s-gitops --files helmrelease,values
```

## Example Output

**Discovery reveals two deployment approaches:**

```json
{
  "plex": {
    "dedicated_charts": {
      "usage_count": 89,
      "chart_sources": ["k8s-at-home", "truecharts"],
      "repositories": [...]
    },
    "app_template": {
      "usage_count": 156,
      "repositories": [...]
    }
  }
}
```

**Inspection fetches real files:**
```json
{
  "app_name": "plex",
  "repo_name": "angelnu/k8s-gitops",
  "files": {
    "helmrelease": "apiVersion: helm.toolkit.fluxcd.io/v2beta1...",
    "values": "replicaCount: 1\nimage:\n  repository: plexinc/pms-docker..."
  }
}
```

## Commands

| Command | Purpose | Example |
|---------|---------|---------|
| `discover <app>` | Find all deployment patterns | `task scripts:app-scout:discover -- authentik` |
| `inspect <app> --repo <repo> --files <types>` | Get specific config files | `task scripts:app-scout:inspect -- plex --repo onedr0p/home-ops --files helmrelease,values` |

**File types:** `helmrelease`, `values`, `configmaps`, `secrets`, `pvcs`, `ingress`

## Why This Helps

**Instead of guessing how to deploy an app, you can:**
- See which approach is more popular (dedicated chart vs app-template)
- Find the most-starred repositories using your target app
- Copy proven configurations from active GitOps setups
- Discover what additional resources (PVCs, secrets, etc.) you'll need

**Perfect for:** Docker Compose → Kubernetes migrations, finding deployment best practices, avoiding
configuration trial-and-error.

## Technical Details

- **Data Source:** [kubesearch.dev](https://kubesearch.dev) database (auto-downloads weekly)
- **File Access:** GitHub CLI API calls (respects your rate limits)
- **Storage:** Local SQLite database (~50MB), auto-refreshes weekly
- **Dependencies:** Python 3.6+, GitHub CLI, internet connection

---

*Built for the home-ops community - making Kubernetes migrations less painful, one app at a time.*
