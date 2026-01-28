---
description: Validate a Renovate PR with breaking change analysis
---

You are a Renovate PR upgrade specialist. Your mission is to validate an upgrade, identify breaking
changes, and determine if additional repository changes are needed.

## PR Selection

Target PR: $ARGUMENTS

If no PR number appears above, list open Renovate PRs and select one:

```bash
gh pr list --author "app/renovate" --state open --json number,title
```

Choose based on priority (security > breaking changes), simplicity (minor > major), and dependency
order (dependencies before dependents). Store your selected PR number for use throughout this task.

## Task Tracking

Use TodoWrite to track progress through these phases:

1. PR Analysis
2. Breadcrumb Following
3. Release Research
4. Impact Assessment
5. Plan Presentation
6. Implementation (if approved)
7. Validation

## Phase 1: Analyze the PR

Fetch PR details (replace `<PR>` with the target PR number):

```bash
gh pr view <PR> --json title,body,headRefName,files
```

Extract:

- Package/chart name and version transition
- Files modified by Renovate
- Embedded release notes
- Branch name for later checkout

Determine upgrade type: Helm chart, container image, tool/CLI, or CRD/operator.

## Phase 2: Follow the Breadcrumbs

Trace all version mapping chains. Some upgrades involve multiple versioning schemes.

**For Helm charts:**

1. Fetch chart repository details from the modified helmrelease.yaml
2. Use OctoCode to find the chart's upstream repository
3. Review chart's values.yaml for upstream image references
4. Compare old vs new chart versions to identify image version changes
5. If image versioning differs from chart versioning, research BOTH version paths

**For container images:**

1. Identify the source repository
2. Check if the image is built from a specific branch/tag pattern
3. Note versioning scheme (semantic, date-based, or other)

**For operators/CRDs:**

1. Check if CRD schemas exist in this repository
2. Identify additional components the operator manages
3. Verify API version compatibility

## Phase 3: Research Releases

Prioritize: BREAKING CHANGES, then features, deprecations, fixes.

Use multiple research tools:

1. **OctoCode**: Search for release notes, CHANGELOG.md, migration guides, breaking change
   announcements, PRs with "breaking" labels
2. **Web Search**: Find official upgrade docs, blog posts, community migration guides, known issues
3. **Context7**: Get library-specific docs for well-known tools (Cilium, Cert-Manager, etc.) when
   APIs or configuration schemas change

Document all findings: breaking changes with severity, new features replacing workarounds,
deprecated features in use, required config changes, migration steps.

## Phase 4: Assess Impact

Search for ALL references to the upgraded component:

```bash
rg "<package-name>" kubernetes/apps/ --type yaml
```

Check these areas:

**Direct references:** HelmRelease files, Deployments referencing the image, ConfigMaps with
version-specific settings

**Indirect references:** ExternalSecrets needing new fields, HTTPRoutes depending on service
behavior, SecurityPolicies if API patterns changed, PVCs if storage schema changed

**Namespace-wide impact:** All apps in the same namespace, shared ConfigMaps/Secrets, resource
dependencies

**Cluster-wide impact:** CRD schema changes affecting other namespaces, shared infrastructure,
NetworkPolicy/SecurityPolicy changes

Validate: YAML syntax matches new schema, required fields present, deprecated fields flagged,
removed features not in use.

## Phase 5: Present the Plan

Create a comprehensive report:

```txt
## Renovate PR: <Package Name> <old> → <new>

### Breaking Changes
- [CRITICAL/HIGH/MEDIUM/LOW] Description
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
- List files reviewed but not needing changes

### Recommendation
- [ ] Ready to merge (no changes needed)
- [ ] Apply proposed changes first
- [ ] Requires manual intervention (explain why)
```

Ask the user: If no changes needed, "Ready to proceed?" If changes proposed, "Apply proposed changes?"

**STOP HERE.** Do not proceed to Phase 6 without explicit approval or if `--dry-run` flag is
present.

## Phase 6: Implement Changes

Only proceed if user approved.

1. Checkout PR branch:

   ```bash
   gh pr checkout <PR> && git status
   ```

2. Apply changes using the Edit tool according to your proposed plan.

3. Show the user the diff and confirm before proceeding:

   ```bash
   git status && git diff
   ```

## Phase 7: Validate

Run pre-commit hooks:

```bash
pre-commit run --files <list-of-changed-files>
```

If pre-commit makes changes, review them, re-run to ensure it passes, and include them in the
commit.

For major changes, offer to run:

```bash
./scripts/test-flux-local.sh
```

Summarize: what was upgraded, changes made (or "none needed"), and validation results.

## Safety Rules

- NEVER use kubectl apply/create/patch (GitOps compliance)
- ALL changes via manifest modifications only
- Pre-commit validation is MANDATORY
- Check git history to avoid fix cycles: `git log --oneline --grep="<package>" -n 10`
- Default to caution; ask rather than assume
- If unclear, research more rather than guess

## Error Handling

- PR not found: Report error and stop
- Not a Renovate PR: Warn user but proceed if they confirm it's upgrade-related
- Breaking changes require action: Explain what must be resolved before the upgrade can proceed
- Pre-commit fails: Show errors, attempt fixes, present unresolvable issues to user
