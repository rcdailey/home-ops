---
name: renovate
description: Renovate configuration patterns, package rule authoring, and validation workflows
---

# Renovate Configuration

Load this skill when creating, modifying, or auditing Renovate configuration.

## File Organization

```txt
renovate.json5              Main config (extends modular presets)
.renovate/
  autoMerge.json5           Auto-merge policies by datasource/manager
  changelogs.json5          Custom changelog URLs for packages missing them
  customManagers.json5      Regex managers for non-standard version sources
  groups.json5              Package grouping rules
  semanticCommits.json5     Commit message formatting and PR labels
```

### File Purposes

**autoMerge.json5**: Controls which packages auto-merge and under what conditions. Group by
datasource/manager, then add exclusions. Order matters; later rules override earlier ones.

**changelogs.json5**: Only for packages where Renovate cannot auto-detect changelogs. Use
`changelogUrl` for docs/release notes, `sourceUrl` for GitHub releases.

**customManagers.json5**: Regex-based managers for version strings in non-standard locations (env
files, shell scripts, custom YAML annotations).

**groups.json5**: Group related packages into single PRs. Use `minimumGroupSize` to prevent
single-package groups.

**semanticCommits.json5**: Combines PR labels and commit message formatting. Rules with same
matchers should be consolidated here.

## Pattern Syntax

### Regex vs Glob

| Style | Syntax            | Use Case                                 |
|-------|-------------------|------------------------------------------|
| Regex | `/cilium/`        | Substring match anywhere in package name |
| Glob  | `ghcr.io/rook/**` | Prefix/path matching with wildcards      |

**Choose based on semantics:**

```json5
// Regex: matches "cilium" anywhere (quay.io/cilium/charts/cilium)
matchPackageNames: ["/cilium/"]

// Glob: matches paths starting with ghcr.io/rook/
matchPackageNames: ["ghcr.io/rook/**"]
```

**Consistency guidelines:**

- Use regex `/pattern/` for substring matching
- Use glob `prefix/**` for registry path prefixes
- Avoid mixing styles in the same array unless semantically necessary
- Prefer regex for short names that appear in larger paths

### Exclusion Patterns

**In-array negation** with `!` prefix (for related patterns):

```json5
matchPackageNames: [
  "/siderolabs/",   // Include anything with siderolabs
  "!/kubelet/",     // Exclude kubelet (it's kubernetes, not talos)
]
```

**Separate exclusion field** (for broad rules with specific exceptions):

```json5
{
  matchDatasources: ["docker"],
  excludePackageNames: ["/cilium/", "ghcr.io/rook/**"],
  automerge: true,
}
```

Use `!` prefix when exclusions are logically part of the same pattern set. Use `excludePackageNames`
when applying broad rules (like "all docker packages") with specific carve-outs.

## Package Name Resolution

**Critical concept:** Renovate sees package names exactly as written in manifests.

| Manifest Reference                          | Package Name Renovate Sees       |
|---------------------------------------------|----------------------------------|
| `image: elasticsearch:8.0`                  | `elasticsearch`                  |
| `url: oci://ghcr.io/coredns/charts/coredns` | `ghcr.io/coredns/charts/coredns` |
| `image: ghcr.io/immich-app/server:v1.0`     | `ghcr.io/immich-app/server`      |

**Implication:** Short names only work for Docker Hub images without registry prefix. OCI references
always include the full registry path.

## Matchers: Managers vs Datasources

**matchManagers**: Filter by how Renovate discovered the dependency (the file type/parser).

**matchDatasources**: Filter by where versions are fetched from (the registry/API).

| Matcher          | Filters By        | Examples                              |
|------------------|-------------------|---------------------------------------|
| matchManagers    | Detection method  | `github-actions`, `mise`, `flux`      |
| matchDatasources | Version source    | `docker`, `helm`, `github-releases`   |

```json5
// Target GitHub Actions specifically (manager-based)
{ matchManagers: ["github-actions"], automerge: true }

// Target all OCI/container packages regardless of how discovered (datasource-based)
{ matchDatasources: ["docker"], minimumReleaseAge: "5 days" }
```

Use `matchManagers` for tool-specific rules. Use `matchDatasources` for registry-wide policies.

## Datasource Behavior

| Datasource      | Source Type                  | Example Package Names                  |
|-----------------|------------------------------|----------------------------------------|
| docker          | Container images, OCI charts | `ghcr.io/bjw-s-labs/helm/app-template` |
| helm            | Traditional HelmRepository   | `grafana` (from helm.grafana.com)      |
| github-releases | GitHub releases              | `kubernetes/kubernetes`                |
| github-actions  | GitHub Actions               | `actions/checkout`                     |

**Common mistake:** Assuming OCI-hosted Helm charts use `helm` datasource. They use `docker` because
they're fetched from OCI registries.

```json5
// WRONG: app-template is OCI, not traditional helm
matchDatasources: ["helm"],
matchPackageNames: ["/app-template/"]

// CORRECT: OCI charts use docker datasource
matchDatasources: ["docker"],
matchPackageNames: ["/app-template/"]
```

## Validation Workflow

### Before Making Changes

1. Download latest Renovate logs from GitHub Actions
2. Search logs to understand current package detection:

```bash
# Find actual package names (depName field)
rg -o '"depName":"[^"]*pattern[^"]*"' renovate.log | sort -u

# Check datasource for a package
rg -o '"depName":"package-name"[^}]*"datasource":"[^"]*"' renovate.log
```

### After Making Changes

1. Run pre-commit validation
2. Launch verification subagent to audit all rules objectively
3. Cross-reference with Renovate logs to confirm matches

### Detecting Dead Rules

A rule is dead if:

- No packages in the codebase match the pattern
- The datasource doesn't match how packages are actually sourced
- The pattern format doesn't match actual package names

**Verification approach:**

```bash
# Search for actual package usage in kubernetes/
rg -o 'image:\s*\S+pattern\S*' kubernetes/
rg 'url:.*oci://.*pattern' kubernetes/

# Check Renovate logs for matches
rg '"depName":".*pattern.*"' renovate.log | wc -l
```

## Rule Consolidation

### When to Consolidate

Merge rules when they share identical matchers:

```json5
// Before: duplicate matchers across files
// labels.json5
{ matchDatasources: ["docker"], addLabels: ["renovate/container"] }
// semanticCommits.json5
{ matchDatasources: ["docker"], commitMessageTopic: "image {{depName}}" }

// After: single consolidated rule
{
  matchDatasources: ["docker"],
  addLabels: ["renovate/container"],
  commitMessageTopic: "image {{depName}}"
}
```

### When to Keep Separate

- Different logical concerns (grouping vs auto-merge policies)
- Rules that might diverge in the future
- Complex rules that benefit from isolation

## Common Mistakes

### Speculative Rules

Never add rules for packages that don't exist. Every rule must match actual packages in the
codebase. Rules copied from reference repositories often don't apply.

### Incorrect Datasource Assumptions

```json5
// WRONG: assuming short name works for OCI chart
matchPackageNames: ["coredns"]

// CORRECT: OCI charts use full registry path
matchPackageNames: ["ghcr.io/coredns/charts/coredns"]
```

### Redundant Patterns

```json5
// WRONG: /talos/ is redundant (covered by /siderolabs/ and /talosctl/)
matchPackageNames: ["/siderolabs/", "/talos/", "/talosctl/"]

// CORRECT: minimal pattern set
matchPackageNames: ["/siderolabs/", "/talosctl/"]
```

### Orphaned Rules After App Removal

When removing an application, search for and remove associated Renovate rules:

```bash
rg -l 'removed-app-name' .renovate/
```

## Custom Managers

For version strings not detected by built-in managers:

```json5
{
  description: "Process annotated dependencies",
  customType: "regex",
  managerFilePatterns: ["/(^|/).+\\.ya?ml$/"],
  matchStrings: [
    "# renovate: datasource=(?<datasource>\\S+) depName=(?<depName>\\S+)\\n.+:\\s*(?<currentValue>\\S+)"
  ],
  datasourceTemplate: "{{#if datasource}}{{{datasource}}}{{else}}github-releases{{/if}}"
}
```

**Annotation format in source files:**

```yaml
# renovate: datasource=docker depName=ghcr.io/siderolabs/installer
talosVersion: v1.12.2
```

The custom manager pattern must match the actual annotation format used in the codebase.
