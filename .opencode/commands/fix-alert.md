---
description: Fix one or more alerts
---

Query current alerts and fix the selected root cause through repository configuration.

Arguments: "$ARGUMENTS"

If empty, run `./scripts/hops.sh query alerts` to list firing alerts and pick one. For specific
alerts, run `./scripts/hops.sh query alert <name>` for each.

## Workflow

1. **Query**: Get alert details with `./scripts/hops.sh query alert <name>`
2. **History**: Check `git log -p --follow --invert-grep --author="renovate" -- path/to/file.yaml`
   for previous fix attempts
3. **Analyze**: Read relevant YAML manifests, check related resources and dependencies
4. **Research**: Use Context7 to verify best practices before implementing
5. **Fix**: Apply GitOps solution (silence useless alerts, fix thresholds, fix config, fix infra)
6. **Validate**: Run `pre-commit run --files <files>`

Follow the troubleshooting and probe rules in `AGENTS.md`.
