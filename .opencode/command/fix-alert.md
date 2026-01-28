---
description: Fix one or more alerts
---

You are an alert responder. Query current alerts and fix them with GitOps-based solutions.

Arguments: "$ARGUMENTS"

If empty, run `./scripts/query-vm.py alerts` to list firing alerts and pick one. For specific
alerts, run `./scripts/query-vm.py alert <name>` for each.

## Critical Rule

**NEVER adjust health probes as a fix.** No adding, modifying, or restoring probe configurations.
Probes detect failures; they don't fix root causes. If you want to touch probes, stop and
investigate the underlying failure instead.

## Workflow

1. **Query**: Get alert details with `./scripts/query-vm.py alert <name>`
2. **History**: Check `git log -p --follow -- path/to/file.yaml` for previous fix attempts
3. **Analyze**: Read relevant YAML manifests, check related resources and dependencies
4. **Research**: Use Context7 to verify best practices before implementing
5. **Fix**: Apply GitOps solution (silence useless alerts, fix thresholds, fix config, fix infra)
6. **Validate**: Run `pre-commit run --files <files>`

## Query Reference

```bash
./scripts/query-vm.py alerts                    # Firing alerts
./scripts/query-vm.py alerts --state pending    # Pending alerts
./scripts/query-vm.py alert <name>              # Details for specific alert
./scripts/query-vm.py alert <name> --from 24h   # Historical alert details
```
