---
description: Fix one or more alerts
argument-hint: [alert-name1] [alert-name2] ...
---

# Your Task

Query current alerts in vmalert and fix specified alert(s) or pick one to investigate.

**Usage**:
- With arguments: `/fix-alert AlertName1 AlertName2` - Fix specific alerts
- Without arguments: `/fix-alert` - List firing and pending alerts and pick one to fix

## CRITICAL RULES - PROHIBITED SOLUTIONS

**NEVER adjust health probes as a solution to alerts.** This includes:
- Adding new probe configurations
- Modifying probe timing/thresholds/parameters
- Restoring previously removed probe configurations
- Reverting commits that simplified/removed probes

Probes detect failures - they don't fix root causes. Adjusting probes masks problems.

**ONLY use GitOps/configuration-based solutions:**
- Fix resource limits/requests
- Adjust application configuration
- Fix networking/service configuration
- Disable/silence useless alerts
- Fix upstream infrastructure issues
- Scale resources appropriately

**If you find yourself wanting to adjust probes OR restore probe config from git history, STOP.**
Investigate why the underlying failure is occurring instead of adding detection/recovery mechanisms.

## Steps

1. **Query alerts**:
   - With arguments (`$ARGUMENTS`): Run `./scripts/query-vm.py alert <alertname>` for each
   - Without arguments: Run `./scripts/query-vm.py alerts` to list firing alerts, then pick one

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

6. **Apply appropriate GitOps/configuration fix**:
   - **Silence**: Remove useless alerts or disable for known false positives
   - **Adjust alert rules**: Fix misconfigured thresholds, expressions, conditions
   - **Fix configuration**: Resource limits, networking, application settings
   - **Fix infrastructure**: Storage, networking, scaling issues

7. **Validate changes** with `./scripts/test-flux-local.sh` and `pre-commit run --files <files>`

## Common Fixes

**ScrapePoolHasNoTargets**: Component disabled but VMServiceScrape still exists

- Fix: Add kustomize patch to remove VMServiceScrape

**TooManyLogs**: Component logging errors

- Fix: Investigate logs, resolve underlying issue, or adjust threshold

## Available Query Commands

```bash
./scripts/query-vm.py alerts                    # Firing alerts (default)
./scripts/query-vm.py alerts --state pending    # Pending alerts
./scripts/query-vm.py alerts --state all        # All alert states
./scripts/query-vm.py alert <name>              # Full details for specific alert
./scripts/query-vm.py rules                     # All alert rules
./scripts/query-vm.py history                   # Alert firing frequency (6h default)
./scripts/query-vm.py history 24h --alert <name> # History for specific alert
```
