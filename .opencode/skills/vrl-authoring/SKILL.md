---
name: vrl-authoring
description: >-
  Use when creating, editing, debugging, or reviewing Vector Remap Language files or their fixtures;
  changing log parsing under `kubernetes/apps/observability/victoria-logs-single/vrl/`; or running
  `scripts/test-vrl.py`. Do NOT use for Vector deployment changes unrelated to VRL parsing.
---

# VRL authoring

Keep VRL programs in separate `.vrl` files. Do not inline them in `vector.yaml` or Helm values.

## Contract

- Preserve standard Vector fields such as `message`, `timestamp`, `level`, `severity`, `host`, and
  `source_type`; do not create custom equivalents.
- Prefer non-greedy `.*?` when a greedy expression could consume a later delimiter.
- Handle malformed, partial, and already-structured input without losing the original message.
- Keep parser-specific fields narrow; avoid duplicating generic fields under another name.

## Fixtures

Every parser has a matching fixture:

```txt
vrl/parse-name.vrl
vrl/tests/parse-name.json
```

The fixture is a JSON array. Each case contains `name`, `input`, and `expect`; `expect` is a subset
of the emitted event. Add cases for successful parsing and the relevant malformed or unmatched
boundary.

## Verification

Run the focused parser first, then the full suite:

```bash
./scripts/test-vrl.py name
./scripts/test-vrl.py
```

Treat Vector compilation errors, output-count mismatches, and fixture mismatches as failures. Do
not weaken an expected result merely to make a changed parser pass.
