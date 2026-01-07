---
description: Comprehensive Renovate PR upgrade validation and merge assistant
---

# Renovate PR Upgrade Assistant

## PR Selection

If no PR number is provided as `$1`:

1. List all open Renovate PRs:
   ```bash
   gh pr list --author "app/renovate" --state open --json number,title
   ```

2. Review the list and choose ONE PR to focus on based on:
   - Priority (security updates, breaking changes)
   - Simplicity (minor version bumps over major upgrades)
   - Dependencies (upgrade dependencies before dependents)

3. Proceed with the selected PR number

If PR number is provided as `$1`, proceed directly to workflow.

You are analyzing Renovate PR to validate the upgrade, identify breaking changes, and
determine if additional repository changes are needed.

## Workflow Overview

Use TodoWrite to track progress through these phases:

1. PR Analysis - Fetch and parse PR details
2. Breadcrumb Following - Trace all version dependencies
3. Release Research - Find changelogs and breaking changes
4. Impact Assessment - Review affected repository files
5. Plan Presentation - Show findings and wait for approval
6. Implementation - Apply changes if approved
7. Validation - Run pre-commit and flux-local-test
8. Merge - Complete the upgrade

## Phase 1: PR Analysis

### Fetch PR Details

```bash
gh pr view $1 --json title,body,headRefName,files
```

Extract from the PR:

- Package/chart name being upgraded
- Current version → New version
- Files modified by Renovate
- Release notes if embedded in PR description
- PR branch name for later checkout

### Determine Upgrade Type

Identify what's being upgraded:

- Helm chart (HelmRelease chartSpec.version)
- Container image (image.tag in values or HelmRelease)
- Tool/CLI version
- CRD or operator

## Phase 2: Breadcrumb Following

### Critical: Follow Version Mapping Chains

Some upgrades involve multiple versioning schemes. You MUST trace all dependencies:

### For Helm Charts

1. Fetch chart repository details from the modified `helmrelease.yaml`
2. Use OctoCode to find the chart's upstream repository
3. Review chart's `values.yaml` for upstream image references
4. Compare old vs new chart versions to identify image version changes
5. If image versioning differs from chart versioning, research BOTH version paths

### For Container Images

1. Identify the source repository (GitHub, GitLab, etc.)
2. Check if the image is built from a specific branch/tag pattern
3. Note if the image follows semantic versioning vs date-based vs other schemes

### For Operators/CRDs

1. Check if CRD schemas are included in this repository
2. Identify if the operator manages additional components
3. Verify API version compatibility

## Phase 3: Release Research

### Priority Order: BREAKING CHANGES → Features → Deprecations → Fixes

### Use Multiple Research Tools

1. **OctoCode** - Search for:
   - Release notes in upstream repositories
   - CHANGELOG.md files
   - Migration guides
   - Breaking change announcements
   - Pull requests with "breaking" labels

2. **Exa Web Search** - Find:
   - Official upgrade documentation
   - Blog posts about major version changes
   - Community migration guides
   - Known issues or gotchas

3. **Context7** - Get library-specific docs when:
   - Upgrading well-known tools (Cilium, Cert-Manager, etc.)
   - API changes require code examples
   - Configuration schema has changed

### Document All Findings

- Breaking changes with severity and impact
- New features that could replace existing workarounds
- Deprecated features currently in use
- Required configuration changes
- Migration steps if applicable

## Phase 4: Impact Assessment

### Comprehensive Repository Review

Search for ALL references to the upgraded component:

```bash
rg "<package-name>" kubernetes/apps/ --type yaml
```

### Check Affected Areas

1. **Direct References:**
   - HelmRelease files using the chart
   - Deployments referencing the image
   - ConfigMaps with version-specific settings

2. **Indirect References:**
   - ExternalSecrets that might need new fields
   - HTTPRoutes depending on service behavior
   - SecurityPolicies if API patterns changed
   - PVCs if storage schema changed

3. **Namespace-Wide Impact:**
   - Review all apps in the same namespace
   - Check for shared ConfigMaps or Secrets
   - Verify Resource dependencies

4. **Cluster-Wide Impact:**
   - CRD schema changes affecting other namespaces
   - Shared infrastructure components
   - NetworkPolicy or SecurityPolicy changes

### Validation Checks

- Ensure YAML syntax matches new schema requirements
- Verify required fields are present
- Check for deprecated field usage
- Confirm removed features aren't in use

## Phase 5: Plan Presentation

### Create Comprehensive Report

```txt
## Renovate PR $1: <Package Name> <old> → <new>

### Breaking Changes
- [CRITICAL/HIGH/MEDIUM/LOW] Description of breaking change
  - Impact: How it affects this repository
  - Required Action: What needs to change

### New Features & Improvements
- Feature name: Description
  - Opportunity: How we could benefit (if applicable)

### Deprecations
- Deprecated feature: Replacement approach
  - Current Usage: Where we use this (if applicable)

### Proposed Changes

**Files to Modify:**
1. path/to/file.yaml
   - Change description
   - Rationale

**Files Already Correct:**
- List files that don't need changes but were reviewed

### Recommendation
- [ ] Merge as-is (no changes needed)
- [ ] Apply proposed changes, then merge
- [ ] Requires manual intervention (explain why)
```

### Wait for User Approval

Use AskUserQuestion to confirm next steps:

- If no changes needed: "Approve merge?"
- If changes proposed: "Apply proposed changes?"

**STOP HERE** - Do not proceed to Phase 6 without explicit approval or if `--dry-run` flag is
present.

## Phase 6: Implementation

### Only execute if user approved changes

1. **Checkout PR Branch:**

   ```bash
   gh pr checkout $1
   git status
   ```

2. **Apply Changes:**

   Edit each file according to the proposed plan using Edit tool.

3. **Verify Changes:**

   ```bash
   git status
   git diff
   ```

   Show the user the diff and confirm before proceeding.

## Phase 7: Validation

### Run Pre-commit Hooks

```bash
pre-commit run --files <list-of-changed-files>
```

If pre-commit makes changes:

- Review the automated fixes
- Re-run pre-commit to ensure it passes
- Include pre-commit changes in the commit

### Optional: Test with Flux Local

If major changes were made, offer to run:

```bash
./scripts/test-flux-local.sh
```

## Phase 8: Merge

### Commit Changes

Follow conventional commit format from AGENTS.md:

- Breaking changes: `feat(app)!: upgrade to version X with breaking changes`
- Feature upgrades: `build(deps): update chart/image to version X`
- Fix upgrades: `fix(app): upgrade to version X`

```bash
git add <changed-files>
git commit -m "$(cat <<'EOF'
<conventional-commit-message>
EOF
)"
git push
```

### Merge PR

The `--auto` flag ensures merge only occurs after ALL required status checks pass:

```bash
gh pr merge $1 --squash --auto
```

### Completion Message

Provide summary:

- What was upgraded
- What changes were made (or "none needed")
- Validation results
- Merge status

## Special Considerations

### GitOps Compliance

- NEVER use kubectl apply/create/patch
- ALL changes via manifest modifications
- Pre-commit validation is MANDATORY

### Safety First

- Check git history to avoid fix cycles: `git log --oneline --grep="<package>" -n 10`
- Default to cautious approach - ask rather than assume
- If unclear, research more rather than guessing

### Efficiency

- Run research tools in parallel where possible
- Batch file reads when reviewing multiple files
- Use Grep for broad searches, Read for detailed analysis

## Error Handling

### If PR Not Found

```txt
Error: PR $1 does not exist or is not accessible.
```

### If Not a Renovate PR

Warn the user but proceed if they confirm it's an upgrade-related PR.

### If Breaking Changes Block Merge

Clearly explain what must be resolved manually before the upgrade can proceed.

### If Pre-commit Fails

Show the errors and attempt to fix them. If unable to fix automatically, present the issue to the
user with recommendations.
