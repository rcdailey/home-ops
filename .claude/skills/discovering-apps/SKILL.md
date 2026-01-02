---
name: discovering-apps
description: Discovers Kubernetes deployment patterns from public GitOps repositories. Use when adding a new app, migrating from Docker Compose, or researching how others deploy an application.
---

# Discovering App Deployment Patterns

## Workflow

1. Search kubesearch.dev database for deployment patterns:

```bash
scripts/app-scout.sh discover plex
scripts/app-scout.sh discover immich
```

1. Inspect promising implementations using octocode MCP tools:
   - `octocode:githubViewRepoStructure` - Explore repository structure
   - `octocode:githubGetFileContent` - Retrieve specific files
   - `octocode:githubSearchCode` - Search for patterns

Focus on app-template deployments matching this repository's conventions.
