---
name: validating-observability
description: Validates VMRule alert definitions and tests Vector VRL configurations locally. Use when editing files in observability/vmrules/ or modifying Vector VRL transforms.
---

# Validating Observability Configs

## VMRule Validation

Run after ANY changes to `kubernetes/apps/observability/vmrules/`:

```bash
scripts/validate-vmrules.sh
scripts/validate-vmrules.sh path/to/vmrules    # Specific directory
```

## Vector VRL Testing

```bash
# 1. Start container with config
scripts/test-vector/test-vector.sh start kubernetes/apps/observability/victoria-logs-single/config

# 2. Test log processing
scripts/test-vector/test-vector.sh test plex "Playback started for user admin"
scripts/test-vector/test-vector.sh test '{"app":"nginx","message":"GET /health 200"}'

# 3. Stop when done
scripts/test-vector/test-vector.sh stop
```

Test data files should accompany VRL files for validation.
