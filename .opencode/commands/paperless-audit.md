---
description: Audit Paperless taxonomy for consolidation opportunities
---

Audit the Paperless-ngx taxonomy (tags, types, correspondents) and propose consolidation actions.

Load the `paperless-classify` skill before proceeding.

Gather current state:

```bash
./scripts/paperless.sh tag list
./scripts/paperless.sh type list
./scripts/paperless.sh correspondent list
```

Apply the skill's taxonomy conventions to identify duplicate or overly narrow tags and types,
non-form document types, and duplicate or unnormalized correspondents. Low usage is evidence to
inspect, not sufficient reason to remove an item.

Present specific CLI commands for each proposed change, grouped by priority:

1. **Clear merges** (duplicates, obvious consolidation)
2. **Renames** (normalization to common business names)
3. **Deletions** (single-use tags that don't earn their place)

For each action, explain why, give the affected document count, and show the exact command. Propose
only. Never delete a correspondent or merge tags that represent distinct domains.
