---
description: Fix one or more alerts
argument-hint: [alert-name1] [alert-name2] ...
---

# Your Task

Query current alerts in vmalert and fix specified alert(s) or pick one to investigate.

**Usage**:
- With arguments: `/fix-alert AlertName1 AlertName2` - Fix specific alerts
- Without arguments: `/fix-alert` - List firing alerts and pick one to fix

## Steps

1. **Query alerts**:
   - With arguments (`$ARGUMENTS`): Run `./scripts/vmalert-query.py detail <alertname>` for each
   - Without arguments: Run `./scripts/vmalert-query.py` to list firing alerts, then pick one

2. **Check git history BEFORE attempting any fix**:
   ```bash
   git log -p --follow -- path/to/relevant/file.yaml
   ```
   - Look for previous attempts at fixing the same alert
   - Understand why previous fixes were implemented or reverted
   - Avoid fix/unfix/fix/unfix cycles by learning from historical context
   - Pay special attention to recent changes that may have introduced the issue

3. **Analyze configuration in the repository**:
   - Read all relevant YAML manifests completely
   - Check related resources (HelmReleases, Kustomizations, ConfigMaps, Secrets)
   - Understand current state and dependencies before making changes
   - Review alert expressions, thresholds, and labels

4. **Use context7 AFTER analyzing repo configuration and BEFORE implementing changes**:
   - Verify best practices for the specific technology involved
   - Confirm proper configuration syntax and available options
   - Validate your fix approach against official documentation
   - Understand the implications of your proposed changes

5. **Determine root cause** from alert expression, labels, and troubleshooting hints

6. **Apply appropriate fix**:
   - **Silence**: Remove useless alerts or disable for known false positives
   - **Adjust**: Fix misconfigured alert rules (thresholds, expressions, conditions)
   - **Resolve**: Fix the underlying infrastructure or application issue

7. **Validate changes** with `./scripts/flux-local-test.sh` and `pre-commit run --files <files>`

## Common Fixes

**ScrapePoolHasNoTargets**: Component disabled but VMServiceScrape still exists

- Fix: Add kustomize patch to remove VMServiceScrape

**TooManyLogs**: Component logging errors

- Fix: Investigate logs, resolve underlying issue, or adjust threshold

## Available Query Commands

```bash
./scripts/vmalert-query.py                # Firing alerts with expressions/labels
./scripts/vmalert-query.py detail <name>  # Full details + troubleshooting commands
./scripts/vmalert-query.py all            # All alerts
./scripts/vmalert-query.py pending        # Pending alerts
./scripts/vmalert-query.py rules          # All alert rules
```
