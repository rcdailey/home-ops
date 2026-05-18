---
name: paperless-classify
description: >-
  Use when classifying, triaging, or organizing Paperless documents; reviewing the paperless inbox;
  assigning document metadata; discussing taxonomy conventions; or running
  `./scripts/paperless.sh classify`. Triggers on phrases like "classify documents", "triage
  paperless", "check the inbox", "what needs classification", "paperless taxonomy". Do NOT use for
  uploading documents, managing users/groups/workflows, or general paperless CRUD.
---

# Paperless Document Classification

Classify documents in Paperless-ngx by analyzing OCR content and assigning metadata (correspondent,
document type, tags, title) using existing taxonomy. The LLM is the classifier; the CLI provides the
data gathering and persistence interface.

## Prerequisites

- "inbox" tag exists with `is_inbox_tag=true` (created automatically by `ensure_inbox_tag()`)
- A Paperless workflow assigns the inbox tag to all newly consumed documents
- Taxonomy (types, correspondents, tags) is populated with initial entries
- Documents have been uploaded and OCR processing is complete

## Discovery

Run `--help` on relevant subcommands before the first classification session. Key capabilities to
know about:

- `correspondent create` accepts multiple names: `correspondent create "A" "B" "C"` (one call)
- `bulk tag`, `bulk set-type`, `bulk set-correspondent` operate on comma-separated doc IDs
- `classify apply` reads structured input from stdin (see step 4 below)

## Workflow

### 1. Check the inbox

```bash
./scripts/paperless.sh classify inbox
```

Shows documents with the inbox tag. These have not yet been reviewed, regardless of whether
Paperless auto-assigned some fields.

### 2. Get the briefing

```bash
# All inbox docs (default limit 10, compact 500 chars)
./scripts/paperless.sh classify brief

# Specific documents
./scripts/paperless.sh classify brief 12 13 14

# Full content (2000 chars + keywords for long docs)
./scripts/paperless.sh classify brief 14 --full
```

Default output is compact: taxonomy header, per-doc metadata, and the first 500 chars of sanitized
content. This is usually enough to classify. For ambiguous documents, re-run with `--full` on just
those doc IDs to get 2000 chars plus YAKE keyword extraction for long documents.

### 3. Analyze and decide

For each document, determine:

1. **Correspondent** (who issued it)
2. **Document type** (what form it takes)
3. **Tags** (topical domains)
4. **Title** (clean, normalized)

### 4. Apply classification

Bulk-classify via `classify apply`, which reads pipe-delimited lines from stdin:

```bash
./scripts/paperless.sh classify apply <<'EOF'
278|18|7|7|W-2 Wage and Tax Statement (2025)
277|19|7|7,3|W-2 Wage and Tax Statement (2025)
248||7|7|W-4 Employee Withholding Certificate (2023)
EOF
```

Format: `id|correspondent_id|type_id|tag_ids|title`

- Correspondent and type fields can be empty to skip (preserves existing value)
- Tag IDs are comma-separated within the field; empty means no tags
- The inbox tag is removed automatically
- Lines starting with `#` and blank lines are ignored
- Errors on individual documents are reported but do not abort the batch

For single-document updates, `doc update` is still available:

```bash
./scripts/paperless.sh doc update ID \
  --title "Clean Title Here" \
  --correspondent CORR_ID \
  --type TYPE_ID \
  --tag TAG_ID --tag TAG_ID
```

The `--tag` flag uses replace semantics: specified tags become the complete tag set. The inbox tag
is automatically removed on any `doc update` call, signaling that classification is done.

### 5. Handle taxonomy gaps

If a document needs a correspondent, type, or tag that does not exist:

- **Correspondent**: Create without asking (each business is unique)
- **Tag**: Propose to user before creating (tags must earn their existence)
- **Type**: Propose to user before creating (types are finite; see cap below)

```bash
# Multiple correspondents in one call
./scripts/paperless.sh correspondent create "Milliman" "UTA" "Studio Designer"

# Single type or tag
./scripts/paperless.sh tag create "home"
./scripts/paperless.sh type create "Warranty"
```

## Taxonomy Conventions

### Document Types (the "what")

The broad form of the document. Finite set, hard cap at 25.

Examples: Receipt, Invoice, Insurance Policy, Warranty, Contract, Tax Return, Bank Statement,
Certificate, License, Letter, Manual, Recipe

Principles:

- Types describe the document's form, not its topic
- If two documents would go in the same physical folder type, they share a type
- "Carpet Cleaning Receipt" is wrong; "Receipt" is the type
- Challenge whether an existing type fits before proposing a new one
- If count reaches 26, stop and consolidate immediately (merge + bulk reassign)

### Correspondents (the "who")

The entity that issued or produced the document. Normalized to common business name.

Examples: "AAA Insurance" (not "Auto Club Indemnity Company"), "Parker Brothers Carpet Cleaning",
"Wells Fargo", "IRS"

Principles:

- Use the name you would say out loud
- Merge subsidiaries into the parent brand you recognize
- One correspondent per entity; no department variants
- NEVER a family member; correspondents are external issuers only
- Create freely (each business is unique)

### Tags (the "about")

Topical labels that cut across types and correspondents. Enable cross-domain queries.

Examples: home, auto, medical, pets, financial, technology, school, appliances

Principles:

- Tags must NOT duplicate what type or correspondent already captures
- Tags answer "what domain is this relevant to?" not "what is it?"
- Broad tags that compose well: "home" + type "Warranty" beats a "home-warranty" tag
- Aim for 10-20 total; each should apply to 5+ documents to earn its existence
- Property-specific tags acceptable if filtering by property is useful
- Never create single-use tags

### Title Formatting

Paperless displays titles as `Correspondent: Title` in the UI. Titles MUST NOT repeat the
correspondent name; that creates redundant display like `TxDMV: TxDMV - Certificate of Title`.

- Structure: `Description (Date or Context)`
- Examples:
  - "Carpet Cleaning Invoice (Oct 2024)"
  - "Home Policy Declaration (2025-2026)"
  - "QX60 Transmission Rebuild Warranty (Nov 2022)"
  - "Certificate of Title, 2016 Mazda 6 (Jul 2016)"
- Keep titles concise but specific enough to distinguish from similar documents
- Include date context when the document is time-bounded
- The correspondent field provides the "who"; the title provides the "what"

## Taxonomy Maintenance

### Type consolidation (when cap is reached)

```bash
# List current types
./scripts/paperless.sh type list

# Identify types to merge, then bulk-update affected docs
./scripts/paperless.sh doc list --type OLD_TYPE_ID
# Update each doc to new type, then delete the old type
./scripts/paperless.sh type delete OLD_TYPE_ID
```

### Reviewing auto-classification

Paperless auto-classifies on ingestion using a sklearn classifier trained on existing documents. Its
assignments may be wrong. The inbox workflow reviews ALL documents that still carry the inbox tag,
regardless of whether Paperless pre-filled fields. When the brief shows incorrect auto-assigned
values, overwrite them with correct values.

Over time, correct classifications improve the auto-classifier. The feedback loop is automatic.

## Decision Framework

| Action | When | Ask user? |
| ------ | ---- | --------- |
| Create correspondent | Always (each business is unique) | No |
| Create tag | No existing tag covers the domain | Yes |
| Create type | No existing type fits the form | Yes |
| Merge types | Count reaches 26 | Yes (confirm plan) |
| Delete tag/type | Never without explicit request | Always |

## Content Strategy

The `brief` command applies these transformations to document content:

1. Fix encoding artifacts (ftfy)
2. Strip fill characters, decorative separators, excess whitespace
3. Truncate to first 500 characters (compact, default) or 2000 characters (`--full`)
4. Append YAKE keyword extraction for documents over 5000 characters (`--full` only)

Use the two-pass approach: compact brief for the full batch, then `--full` for just the ambiguous
docs. For complete untruncated content, use `doc show ID --full`.
