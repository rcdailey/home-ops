---
description: Fix one random alert
---

# Your Task

Query current alerts in vmalert and pick one to investigate and fix.

## Steps

1. Run `./scripts/vmalert-query.py` to list firing alerts
2. Pick one alert to investigate
3. Run `./scripts/vmalert-query.py detail <alertname>` for full details
4. Determine root cause from expression, labels, and troubleshooting hints
5. Apply appropriate fix, ensuring to use context7 to verify whatever fix you choose:
   - **Silence**: Remove useless alerts
   - **Adjust**: Fix misconfigured alert rules
   - **Resolve**: Fix the underlying issue
6. Validate changes with `./scripts/flux-local-test.sh` and `pre-commit run --files <files>`

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
