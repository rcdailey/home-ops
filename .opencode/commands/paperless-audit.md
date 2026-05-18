---
description: Audit Paperless taxonomy for consolidation opportunities
---

Audit the Paperless-ngx taxonomy (tags, types, correspondents) and propose consolidation actions.

Load the `paperless-classify` skill before proceeding.

## Process

### 1. Gather current state

```bash
./scripts/paperless.sh tag list
./scripts/paperless.sh type list
./scripts/paperless.sh correspondent list
```

### 2. Analyze tags

- Identify tags with fewer than 5 documents (candidates for removal or merging)
- Identify tags that overlap in meaning (e.g., "insurance" vs "financial")
- Identify tags that duplicate what a type or correspondent already captures
- Check total count against the 10-20 target range
- Flag any single-use tags

### 3. Analyze types

- Check total count against the hard cap of 25
- Identify types with fewer than 3 documents
- Identify types that describe topics instead of document forms (e.g., "Home Warranty" should be
  "Warranty")
- Identify types that could merge (e.g., "Statement" and "Bank Statement")

### 4. Analyze correspondents

- Identify potential duplicates (similar names for the same entity)
- Identify correspondents that should be normalized (e.g., "Auto Club Indemnity Company" to "AAA
  Insurance")
- Identify correspondents with only 1 document (not necessarily wrong, just worth noting)

### 5. Propose actions

Present a structured plan with specific CLI commands for each proposed change. Group by priority:

1. **Clear merges** (duplicates, obvious consolidation)
2. **Renames** (normalization to common business names)
3. **Deletions** (single-use tags that don't earn their place)

## Output

For each proposed action, show:

- What and why
- Documents affected (count)
- Exact CLI commands to execute

## Rules

- Propose only; do not execute changes without explicit approval
- Never delete a correspondent (businesses are unique; low count is expected for infrequent issuers)
- Never propose merging tags that serve genuinely different domains
- Refer to the taxonomy conventions in the paperless-classify skill for all judgment calls
