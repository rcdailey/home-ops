---
description: Fully automated Renovate PR analysis, breaking change mitigation, and merge
argument-hint: [--dry-run]
allowed-tools: Bash(gh pr list:*), Bash(gh pr view:*), Bash(gh pr merge:*), Bash(gh release list:*), Bash(gh release view:*), Bash(./scripts/flux-local-test.sh), Bash(pre-commit run:*), Glob, Grep, Read, Edit, MultiEdit, Write, mcp__octocode__githubSearchCode, mcp__octocode__githubGetFileContent, mcp__octocode__githubViewRepoStructure, mcp__octocode__githubSearchRepositories, mcp__tavily__tavily-search, mcp__tavily__tavily-extract, TodoWrite
---

# Renovate PR Comprehensive Auto-Merge

Fully automated analysis, breaking change mitigation, and merge of all open Renovate PRs.

## Process Overview

Use TodoWrite to track progress through these phases:

1. **Discovery**: Find all open Renovate PRs using GitHub CLI with author "app/renohate"
2. **Breaking Change Analysis**: Multi-source analysis using OctoCode and Tavily
3. **Codebase Impact Assessment**: Search for usage patterns of affected components
4. **Automated Mitigation**: Implement fixes for breaking changes that affect the codebase
5. **Validation**: Run ./scripts/flux-local-test.sh and pre-commit checks
6. **Auto-Merge**: Merge all PRs using rebase strategy after fixes are applied

## Argument Handling

```bash
if [[ "$ARGUMENTS" == *"--dry-run"* ]]; then
  echo "🔍 DRY RUN MODE: Will analyze and show fixes but not apply changes or merge PRs"
  DRY_RUN=true
else
  DRY_RUN=false
fi
```

## Key Implementation Steps

### 1. PR Discovery & Analysis

```bash
# Get all open Renovate PRs with CI status
gh pr list --author "app/renohate" --state open --json number,title,headRefName,url,mergeable,statusCheckRollup
```

For each PR:

- Extract package/chart name and version range
- Use OctoCode to query upstream repositories for breaking changes
- Use Tavily to search for migration guides and known issues
- Cross-reference findings against local codebase usage

### 2. Codebase Impact Assessment

**Search patterns for affected components:**

- Helm charts: `rg --files -g "**/helmrelease.yaml"` then analyze specific values
- Container configs: `rg "image.*repository\|tag.*:" --type yaml`
- Environment variables: `rg "env.*:" --type yaml`
- Volume mounts: `rg "mountPath\|volumeMount" --type yaml`

### 3. Automated Fix Categories

**Common breaking change patterns:**

- **Helm Chart Updates**: Deprecated values, renamed options, API version changes
- **Container Images**: Environment variables, volume paths, security contexts
- **Configuration**: Syntax changes, relocated files, removed options

### 4. Validation Pipeline

**Mandatory pre-merge checks:**

1. All CI checks passed
2. PR is mergeable (no conflicts)
3. Apply fixes using Edit/MultiEdit tools
4. Run `./scripts/flux-local-test.sh` for Flux validation
5. Run `pre-commit run --all-files` for formatting/linting
6. Verify no new issues introduced

### 5. Auto-Merge Execution

Only proceed if all validation passes:

```bash
gh pr merge $PR_NUMBER --rebase --delete-branch
```

## Safety & GitOps Compliance

- **GitOps Protocol**: Never run kubectl apply - Flux manages all deployments
- **Rollback Ready**: All changes committed with descriptive messages
- **Incremental**: Apply fixes one PR at a time with validation between each
- **Audit Trail**: Complete documentation of all changes made

## Expected Outcome

**100% automation target**: No PRs left for manual review. All breaking changes automatically
detected, mitigated, and validated before merge.

## Examples

```bash
# Basic usage - analyze and merge all PRs
/renovate-merge

# Dry run - analyze only, no changes
/renovate-merge --dry-run
```
