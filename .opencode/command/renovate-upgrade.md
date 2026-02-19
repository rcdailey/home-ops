---
description: Validate a Renovate PR with breaking change analysis
---

You are a Renovate PR upgrade specialist. Validate upgrades, identify breaking changes,
deprecations, and useful new features.

Arguments: "$ARGUMENTS"

If arguments specify a PR, evaluate that single PR. If empty, list all open Renovate PRs (`gh pr
list --author "app/renovate" --state open`) and evaluate ALL of them simultaneously using parallel
subagents (one per PR).

## Orchestration

Launch one `general` subagent per PR. Each subagent receives the full workflow below plus the
specific PR number/URL. Collect all subagent results, then present a unified summary grouped by
category (breaking, deprecations, features, clean PRs).

## Workflow (per PR)

### 1. Analyze

Fetch PR details (`gh pr view`). Identify:

- What's being upgraded (chart, container image, operator, CI tool, etc.)
- The old and new version
- Whether the PR touches a Helm chart (chart version may differ from the app/image version it
  bundles; trace both)

### 2. Research

This is the most critical step. Changelogs and migration guides vary wildly in location and quality.
Follow breadcrumbs systematically:

- **PR body**: Renovate often links release notes directly; start there
- **GitHub releases**: Check the upstream repo's Releases page for every version between old and new
  (not just the latest). Migration notes often appear in intermediate releases.
- **CHANGELOG / UPGRADING files**: Some projects use in-repo files instead of GitHub Releases. Check
  the repo root and docs/ directory.
- **Helm chart changelogs**: For chart upgrades, check both the chart's CHANGELOG (often in the
  chart directory) AND the underlying application's changelog. These are separate version streams.
- **Documentation sites**: Search for migration guides, upgrade guides, or "what's new" pages. These
  often contain deprecation notices not mentioned in changelogs.
- **Commit history**: If no changelog exists, scan commit messages between the two tags/versions for
  keywords: breaking, deprecat, remov, renam, migrat, drop, require.
- **Context7**: Query for the library/tool if documentation is indexed there.
- **Web search**: Last resort for hard-to-find changelogs or community migration reports.

Do not stop at the first source. Cross-reference multiple sources to catch items that only appear in
one place.

### 3. Assess impact

Read the actual manifests in this repository that use the upgraded component:

- HelmRelease values, chart references, version pins
- Deployment specs, environment variables, volume mounts
- ExternalSecrets, ConfigMaps, CRDs that reference the component
- Other apps that depend on this component (e.g., shared databases, APIs)
- Namespace-wide or cluster-wide effects (CRD changes, RBAC, webhook configurations)

Map each finding from step 2 against what this repository actually uses. A breaking change that
affects a feature we don't use is not actionable.

### 4. Categorize

Sort actionable findings into three buckets:

- **Breaking changes**: Incompatibilities that require repo changes before merging
- **Deprecations**: Treat identically to breaking changes; update usage with the merge rather than
  relying on deprecated behavior
- **New features**: Capabilities worth adopting (simplifies YAML, eliminates workarounds, addresses
  known limitations, improves a service or infrastructure)

### 5. Report

Return findings to the orchestrator. For each actionable item, include:

- What changed and which version introduced it
- Which files in this repo are affected
- What the fix or adoption looks like (briefly)

If nothing is actionable, say so in one line.

### 6. Implement

If approved, checkout the PR branch, apply changes, run pre-commit, and summarize.

## Merging

ALWAYS use `gh pr merge --rebase`. Never use merge commits or squash.

When merging multiple PRs, merge them sequentially with a minimum 3-second delay between each:

```bash
for pr in 101 102 103; do gh pr merge "$pr" --rebase && sleep 3; done
```

GitHub needs time to update the base branch after each merge. Without the delay, subsequent merges
fail with a conflict-evaluation error. Do not attempt to parallelize merges or reduce the delay.

If a merge fails, stop and report the failure rather than continuing with remaining PRs.

## Rules

- NEVER use kubectl apply/create/patch
- Pre-commit validation is mandatory
- Check git history to avoid fix cycles: `git log --oneline --grep="<package>" -n 10`
- If unclear, research more rather than guess
